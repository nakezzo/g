package parser

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/PuerkitoBio/goquery"

	"poshmark/internal/domain"
)

var usernameCleaner = regexp.MustCompile(`[^a-z0-9._]`)
var manyDots = regexp.MustCompile(`\.{2,}`)
var closetPattern = regexp.MustCompile(`/closet/([^/?#]+)`)
var digitPattern = regexp.MustCompile(`\d+`)

type Parser struct {
	baseURL      string
	cfg          domain.ParserConfig
	client       *http.Client
	logf         func(string)
	seenUsers    map[string]struct{}
	seenItems    map[string]struct{}
	seenMu       sync.Mutex
	proxyIdx     int
	maxSemaphore chan struct{}
	stats        map[string]int
	statsMu      sync.Mutex
}

type rawItem struct {
	URL      string
	Title    string
	Username string
}

func NewPoshmarkParser(cfg domain.ParserConfig, logf func(string)) *Parser {
	return &Parser{
		baseURL: "https://poshmark.com",
		cfg:     cfg,
		client: &http.Client{
			Timeout: 20 * time.Second,
		},
		logf:      logf,
		seenUsers: map[string]struct{}{},
		seenItems: map[string]struct{}{},
		proxyIdx:  cfg.ProxyIdx,
		maxSemaphore: make(chan struct{}, func() int {
			if cfg.MaxConcurrent > 0 {
				return cfg.MaxConcurrent
			}
			return 10
		}()),
		stats: map[string]int{
			"found":  0,
			"valid":  0,
			"errors": 0,
		},
	}
}

func (p *Parser) log(message string) {
	if p.logf != nil {
		p.logf(message)
	}
}

func (p *Parser) incrStat(key string, delta int) {
	p.statsMu.Lock()
	defer p.statsMu.Unlock()
	p.stats[key] += delta
}

func (p *Parser) Stats() map[string]int {
	p.statsMu.Lock()
	defer p.statsMu.Unlock()

	out := make(map[string]int, len(p.stats))
	for k, v := range p.stats {
		out[k] = v
	}
	return out
}

func (p *Parser) nextProxy() string {
	if len(p.cfg.Proxies) == 0 {
		return ""
	}
	proxy := p.cfg.Proxies[p.proxyIdx%len(p.cfg.Proxies)]
	p.proxyIdx = (p.proxyIdx + 1) % len(p.cfg.Proxies)
	return proxy
}

func (p *Parser) headers(req *http.Request) {
	userAgents := []string{
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
		"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
	}
	req.Header.Set("User-Agent", userAgents[rand.Intn(len(userAgents))])
	req.Header.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8")
	req.Header.Set("Accept-Language", "en-US,en;q=0.9")
	req.Header.Set("Connection", "keep-alive")
}

func (p *Parser) fetch(ctx context.Context, targetURL, proxyAddr string) (string, error) {
	p.maxSemaphore <- struct{}{}
	defer func() { <-p.maxSemaphore }()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, targetURL, nil)
	if err != nil {
		return "", err
	}
	p.headers(req)

	transport := &http.Transport{}
	if strings.HasPrefix(proxyAddr, "http://") || strings.HasPrefix(proxyAddr, "https://") {
		parsedProxy, perr := url.Parse(proxyAddr)
		if perr == nil {
			transport.Proxy = http.ProxyURL(parsedProxy)
		}
	}

	client := p.client
	if transport.Proxy != nil {
		client = &http.Client{
			Timeout:   p.client.Timeout,
			Transport: transport,
		}
	}

	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("unexpected status %d", resp.StatusCode)
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return "", err
	}
	html, err := doc.Html()
	if err != nil {
		return "", err
	}
	return html, nil
}

func cleanUsername(username string) string {
	username = strings.ToLower(strings.TrimSpace(username))
	username = usernameCleaner.ReplaceAllString(username, "")
	username = manyDots.ReplaceAllString(username, ".")
	username = strings.Trim(username, ".")
	if len(username) < 2 {
		return ""
	}
	return username
}

func parseNumber(raw string) int {
	match := digitPattern.FindString(raw)
	if match == "" {
		return 0
	}
	value, _ := strconv.Atoi(match)
	return value
}

func (p *Parser) passesFilters(item domain.PoshmarkItem) (bool, string) {
	if p.cfg.MaxSales > 0 && parseNumber(item.SoldCount) > p.cfg.MaxSales {
		return false, fmt.Sprintf("sales %d > %d", parseNumber(item.SoldCount), p.cfg.MaxSales)
	}
	if p.cfg.MaxReviews > 0 && parseNumber(item.ReviewsCount) > p.cfg.MaxReviews {
		return false, fmt.Sprintf("reviews %d > %d", parseNumber(item.ReviewsCount), p.cfg.MaxReviews)
	}
	return true, ""
}

func (p *Parser) parseFeedPage(html string) []rawItem {
	result := make([]rawItem, 0, 64)
	seen := map[string]struct{}{}

	doc, err := goquery.NewDocumentFromReader(strings.NewReader(html))
	if err != nil {
		return result
	}

	doc.Find("script[type='application/json']").Each(func(_ int, sel *goquery.Selection) {
		rawJSON := strings.TrimSpace(sel.Text())
		if rawJSON == "" {
			return
		}
		var payload map[string]any
		if err := json.Unmarshal([]byte(rawJSON), &payload); err != nil {
			return
		}
		walkForListings(payload, &result, seen, p.baseURL)
	})

	if len(result) > 0 {
		return result
	}

	doc.Find("a[href*='/closet/']").Each(func(_ int, sel *goquery.Selection) {
		href, _ := sel.Attr("href")
		match := closetPattern.FindStringSubmatch(href)
		if len(match) != 2 {
			return
		}
		username := cleanUsername(match[1])
		if username == "" {
			return
		}
		key := "u:" + username
		if _, ok := seen[key]; ok {
			return
		}
		seen[key] = struct{}{}
		result = append(result, rawItem{
			Username: username,
			URL:      "",
			Title:    "",
		})
	})

	return result
}

func walkForListings(node any, result *[]rawItem, seen map[string]struct{}, baseURL string) {
	switch value := node.(type) {
	case map[string]any:
		if creatorValue, ok := value["creator"]; ok {
			if creatorMap, ok := creatorValue.(map[string]any); ok {
				username, _ := creatorMap["login"].(string)
				if username == "" {
					username, _ = creatorMap["username"].(string)
				}
				if username != "" {
					cleaned := cleanUsername(username)
					if cleaned != "" {
						title, _ := value["title"].(string)
						idRaw, hasID := value["id"]
						if hasID {
							id := fmt.Sprint(idRaw)
							key := "i:" + id + ":" + cleaned
							if _, exists := seen[key]; !exists {
								seen[key] = struct{}{}
								*result = append(*result, rawItem{
									URL:      baseURL + "/listing/" + id,
									Title:    title,
									Username: cleaned,
								})
							}
						}
					}
				}
			}
		}
		for _, child := range value {
			walkForListings(child, result, seen, baseURL)
		}
	case []any:
		for _, child := range value {
			walkForListings(child, result, seen, baseURL)
		}
	}
}

func (p *Parser) getUserDetails(ctx context.Context, username, proxyAddr string) (sold, listings, reviews string) {
	closetURL := p.baseURL + "/closet/" + username
	html, err := p.fetch(ctx, closetURL, proxyAddr)
	if err != nil || html == "" {
		return "", "", ""
	}

	doc, err := goquery.NewDocumentFromReader(strings.NewReader(html))
	if err != nil {
		return "", "", ""
	}
	text := doc.Text()

	soldMatch := regexp.MustCompile(`(?i)(\d[\d,]*)\s*Sold`).FindStringSubmatch(text)
	listingsMatch := regexp.MustCompile(`(?i)(\d[\d,]*)\s*Listings`).FindStringSubmatch(text)
	reviewsMatch := regexp.MustCompile(`(?i)(\d[\d,]*)\s*(Followers|Love)`).FindStringSubmatch(text)

	if len(soldMatch) > 1 {
		sold = soldMatch[1]
	}
	if len(listingsMatch) > 1 {
		listings = listingsMatch[1]
	}
	if len(reviewsMatch) > 1 {
		reviews = reviewsMatch[1]
	}

	return sold, listings, reviews
}

func (p *Parser) processRaw(ctx context.Context, raw rawItem, proxyAddr string) (domain.PoshmarkItem, bool) {
	username := cleanUsername(raw.Username)
	if username == "" {
		return domain.PoshmarkItem{}, false
	}

	p.seenMu.Lock()
	if _, exists := p.seenUsers[username]; exists {
		p.seenMu.Unlock()
		return domain.PoshmarkItem{}, false
	}
	if raw.URL != "" {
		if _, exists := p.seenItems[raw.URL]; exists {
			p.seenMu.Unlock()
			return domain.PoshmarkItem{}, false
		}
	}
	p.seenMu.Unlock()

	sold, listings, reviews := p.getUserDetails(ctx, username, proxyAddr)
	item := domain.PoshmarkItem{
		Username:      username,
		Email:         username + "@gmail.com",
		ItemTitle:     raw.Title,
		ItemURL:       raw.URL,
		SoldCount:     sold,
		ListingsCount: listings,
		ReviewsCount:  reviews,
	}

	ok, reason := p.passesFilters(item)
	if !ok {
		p.log("skip " + username + ": " + reason)
		return domain.PoshmarkItem{}, false
	}

	p.seenMu.Lock()
	p.seenUsers[username] = struct{}{}
	if raw.URL != "" {
		p.seenItems[raw.URL] = struct{}{}
	}
	p.seenMu.Unlock()

	p.incrStat("valid", 1)
	return item, true
}

func (p *Parser) watchCategory(ctx context.Context, category string, out chan<- domain.PoshmarkItem) {
	ticker := time.NewTicker(time.Duration(p.cfg.CycleDelay * float64(time.Second)))
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		proxyAddr := p.nextProxy()
		targetURL := p.baseURL + category + "?sort_by=added_desc"
		html, err := p.fetch(ctx, targetURL, proxyAddr)
		if err != nil {
			p.incrStat("errors", 1)
			p.log(fmt.Sprintf("fetch %s failed: %v", category, err))
		} else {
			items := p.parseFeedPage(html)
			limit := p.cfg.ItemsPerPage
			if limit <= 0 || limit > len(items) {
				limit = len(items)
			}
			for i := 0; i < limit; i++ {
				select {
				case <-ctx.Done():
					return
				default:
				}
				p.incrStat("found", 1)
				item, ok := p.processRaw(ctx, items[i], proxyAddr)
				if ok {
					out <- item
				}
				time.Sleep(time.Duration(p.cfg.RequestDelay * float64(time.Second)))
			}
		}

		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func (p *Parser) Start(ctx context.Context, out chan<- domain.PoshmarkItem) {
	p.log(fmt.Sprintf("parser started: categories=%d proxies=%d", len(p.cfg.SelectedCategories), len(p.cfg.Proxies)))

	var wg sync.WaitGroup
	for _, category := range p.cfg.SelectedCategories {
		cat := category
		wg.Add(1)
		go func() {
			defer wg.Done()
			p.watchCategory(ctx, cat, out)
		}()
	}

	wg.Wait()
	close(out)
}
