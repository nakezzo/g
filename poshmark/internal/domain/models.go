package domain

type Account struct {
	Email      string `json:"email"`
	Password   string `json:"password"`
	Enabled    bool   `json:"enabled"`
	SentCount  int    `json:"sent_count"`
	ErrorCount int    `json:"error_count"`
	LastError  string `json:"last_error"`
	SendLimit  int    `json:"send_limit"`
}

type SentLog struct {
	FromEmail string `json:"from_email"`
	ToEmail   string `json:"to_email"`
	Subject   string `json:"subject"`
	Status    string `json:"status"`
	Timestamp string `json:"timestamp"`
	Error     string `json:"error"`
}

type PoshmarkItem struct {
	Username      string `json:"username"`
	Email         string `json:"email"`
	ItemTitle     string `json:"item_title"`
	ItemURL       string `json:"item_url"`
	SoldCount     string `json:"sold_count"`
	Price         string `json:"price"`
	ListingsCount string `json:"listings_count"`
	ReviewsCount  string `json:"reviews_count"`
}

type APIParserSettings struct {
	Token       string `json:"token"`
	Enabled     bool   `json:"enabled"`
	Platform    string `json:"platform"`
	Country     string `json:"country"`
	Category    string `json:"category"`
	Price       string `json:"price"`
	Limit       int    `json:"limit"`
	AutoSend    bool   `json:"auto_send"`
	Interval    int    `json:"interval"`
	Publication string `json:"publication"`
	Reviews     string `json:"reviews"`
	Ads         string `json:"ads"`
	Sells       string `json:"sells"`
	Buys        string `json:"buys"`
	Blacklist   string `json:"blacklist"`
	EmailOnly   bool   `json:"email_only"`
	TotalFound  int    `json:"total_found"`
	LastRun     string `json:"last_run"`
}

type ParserConfig struct {
	SelectedCategories []string       `json:"selected_categories"`
	CycleDelay         float64        `json:"cycle_delay"`
	RequestDelay       float64        `json:"request_delay"`
	MaxConcurrent      int            `json:"max_concurrent"`
	ItemsPerPage       int            `json:"items_per_page"`
	MaxSales           int            `json:"max_sales"`
	MaxReviews         int            `json:"max_reviews"`
	AutoSend           bool           `json:"auto_send"`
	DelayMin           int            `json:"delay_min"`
	DelayMax           int            `json:"delay_max"`
	Proxies            []string       `json:"proxies"`
	ProxyIdx           int            `json:"proxy_idx"`
	RotateEvery        map[string]int `json:"rotate_every"`
	SendCounter        int            `json:"send_counter"`
}

func DefaultAccount() Account {
	return Account{
		Enabled: true,
	}
}

func DefaultAPIParserSettings() APIParserSettings {
	return APIParserSettings{
		Token:       "",
		Enabled:     false,
		Platform:    "vinted",
		Country:     "DE",
		Category:    "",
		Price:       "1..",
		Limit:       50,
		AutoSend:    true,
		Interval:    60,
		Publication: "",
		Reviews:     "",
		Ads:         "",
		Sells:       "",
		Buys:        "",
		Blacklist:   "",
		EmailOnly:   true,
		TotalFound:  0,
		LastRun:     "",
	}
}

func DefaultParserConfig(categories []string) ParserConfig {
	return ParserConfig{
		SelectedCategories: categories,
		CycleDelay:         2.0,
		RequestDelay:       0.3,
		MaxConcurrent:      10,
		ItemsPerPage:       30,
		MaxSales:           0,
		MaxReviews:         0,
		AutoSend:           true,
		DelayMin:           17,
		DelayMax:           24,
		Proxies:            []string{},
		ProxyIdx:           0,
		RotateEvery: map[string]int{
			"sender":  0,
			"title":   0,
			"text":    0,
			"button":  0,
			"link":    0,
			"subject": 0,
		},
		SendCounter: 0,
	}
}
