package bot

import (
	"context"
	"fmt"
	"html"
	"log"
	"math/rand"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"

	"poshmark/internal/access"
	"poshmark/internal/config"
	"poshmark/internal/domain"
	"poshmark/internal/parser"
	"poshmark/internal/smtp"
	"poshmark/internal/storage"
)

var emailPattern = regexp.MustCompile(`[\w.+\-]+@[\w.\-]+\.\w+`)

type parserSession struct {
	cancel    context.CancelFunc
	parser    *parser.Parser
	startedAt time.Time
	autoSend  bool
}

type sendSession struct {
	cancel context.CancelFunc
}

type Service struct {
	cfg   config.AppConfig
	store *storage.JSONStore
	tg    *Client
	acl   *access.ACL

	mu      sync.Mutex
	parsers map[int64]*parserSession
	sends   map[int64]*sendSession
}

func NewService(cfg config.AppConfig) (*Service, error) {
	rand.Seed(time.Now().UnixNano())
	acl, err := access.NewACL(cfg.DataDir, cfg.BotAdminIDs)
	if err != nil {
		return nil, err
	}
	return &Service{
		cfg:     cfg,
		store:   storage.NewJSONStore(cfg),
		tg:      NewClient(cfg.BotToken),
		acl:     acl,
		parsers: map[int64]*parserSession{},
		sends:   map[int64]*sendSession{},
	}, nil
}

func (s *Service) Run(ctx context.Context) error {
	offset := 0
	for {
		select {
		case <-ctx.Done():
			return nil
		default:
		}

		updates, err := s.tg.GetUpdates(offset)
		if err != nil {
			log.Printf("telegram polling error: %v", err)
			time.Sleep(2 * time.Second)
			continue
		}

		for _, upd := range updates {
			if upd.UpdateID >= offset {
				offset = upd.UpdateID + 1
			}
			if upd.Message == nil {
				continue
			}
			go s.handleMessage(ctx, *upd.Message)
		}
	}
}

func (s *Service) handleMessage(ctx context.Context, msg Message) {
	text := strings.TrimSpace(msg.Text)
	if text == "" {
		return
	}
	if !strings.HasPrefix(text, "/") {
		_ = s.reply(msg.Chat.ID, "Use /help to see available commands.")
		return
	}

	cmdToken := strings.Fields(text)[0]
	cmd := strings.ToLower(strings.SplitN(cmdToken, "@", 2)[0])
	args := strings.TrimSpace(strings.TrimPrefix(text, cmdToken))
	userID := strconv.FormatInt(msg.From.ID, 10)
	isAdmin := s.acl.IsAdmin(msg.From.ID)
	hasAccess := s.acl.HasAccess(msg.From.ID)

	if !hasAccess && cmd != "/start" && cmd != "/help" && cmd != "/whoami" {
		_ = s.reply(msg.Chat.ID, fmt.Sprintf("Access denied.\nYour Telegram ID: <code>%d</code>\nAsk admin to run: <code>/grant %d</code>", msg.From.ID, msg.From.ID))
		return
	}

	switch cmd {
	case "/start", "/help":
		_ = s.reply(msg.Chat.ID, s.helpText(isAdmin, hasAccess))
	case "/whoami":
		s.cmdWhoAmI(msg.Chat.ID, msg.From.ID, hasAccess, isAdmin)
	case "/grant":
		s.cmdGrant(msg.Chat.ID, isAdmin, args)
	case "/revoke":
		s.cmdRevoke(msg.Chat.ID, isAdmin, args)
	case "/access_list":
		s.cmdAccessList(msg.Chat.ID, isAdmin)
	case "/accounts":
		s.cmdAccounts(msg.Chat.ID, userID)
	case "/account_add":
		s.cmdAccountAdd(msg.Chat.ID, userID, args)
	case "/account_toggle":
		s.cmdAccountToggle(msg.Chat.ID, userID, args)
	case "/account_limit":
		s.cmdAccountLimit(msg.Chat.ID, userID, args)
	case "/account_delete":
		s.cmdAccountDelete(msg.Chat.ID, userID, args)
	case "/vars":
		s.cmdVars(msg.Chat.ID, userID)
	case "/var_set":
		s.cmdVarSet(msg.Chat.ID, userID, args)
	case "/subjects":
		s.cmdSubjects(msg.Chat.ID, userID)
	case "/subjects_set":
		s.cmdSubjectsSet(msg.Chat.ID, userID, args)
	case "/templates":
		s.cmdTemplates(msg.Chat.ID, userID)
	case "/template_set":
		s.cmdTemplateSet(msg.Chat.ID, userID, args)
	case "/template_select":
		s.cmdTemplateSelect(msg.Chat.ID, userID, args, true)
	case "/template_unselect":
		s.cmdTemplateSelect(msg.Chat.ID, userID, args, false)
	case "/template_delete":
		s.cmdTemplateDelete(msg.Chat.ID, userID, args)
	case "/delay":
		s.cmdDelay(msg.Chat.ID, userID, args)
	case "/rotation_set":
		s.cmdRotationSet(msg.Chat.ID, userID, args)
	case "/send":
		s.cmdSend(msg.Chat.ID, userID, args)
	case "/send_stop":
		s.cmdSendStop(msg.Chat.ID, msg.From.ID)
	case "/parser_start":
		s.cmdParserStart(ctx, msg.Chat.ID, msg.From.ID, userID)
	case "/parser_stop":
		s.cmdParserStop(msg.Chat.ID, msg.From.ID)
	case "/parser_status":
		s.cmdParserStatus(msg.Chat.ID, msg.From.ID)
	case "/parser_auto":
		s.cmdParserAuto(msg.Chat.ID, msg.From.ID, userID, args)
	case "/parser_categories":
		s.cmdParserCategories(msg.Chat.ID, userID, args)
	case "/proxy_set":
		s.cmdProxySet(msg.Chat.ID, userID, args)
	case "/proxy_clear":
		s.cmdProxyClear(msg.Chat.ID, userID)
	case "/api_list":
		s.cmdAPIList(msg.Chat.ID, userID)
	case "/api_enable":
		s.cmdAPIEnable(msg.Chat.ID, userID, args)
	case "/api_set":
		s.cmdAPISet(msg.Chat.ID, userID, args)
	case "/logs":
		s.cmdLogs(msg.Chat.ID, userID)
	default:
		_ = s.reply(msg.Chat.ID, "Unknown command. Use /help.")
	}
}

func (s *Service) helpText(isAdmin bool, hasAccess bool) string {
	if !hasAccess {
		return strings.Join([]string{
			"<b>Access required</b>",
			"",
			"This bot is private.",
			"Send your Telegram ID to admin:",
			"<code>/whoami</code>",
		}, "\n")
	}

	return strings.Join([]string{
		"<b>Poshmark Go Bot</b>",
		fmt.Sprintf("Access: %t | Admin: %t", hasAccess, isAdmin),
		"",
		"<b>Access</b>",
		"/whoami",
		"<b>Accounts</b>",
		"/accounts",
		"/account_add email password",
		"/account_toggle email",
		"/account_limit email limit",
		"/account_delete email",
		"",
		"<b>Content</b>",
		"/vars",
		"/var_set key value1 | value2",
		"/subjects",
		"/subjects_set subject1 | subject2",
		"/templates",
		"/template_set name &lt;html&gt;",
		"/template_select name",
		"/template_unselect name",
		"/template_delete name",
		"",
		"<b>Sending</b>",
		"/delay min max",
		"/rotation_set key every",
		"/send email1 email2 ...",
		"/send_stop",
		"/logs",
		"",
		"<b>Parser</b>",
		"/parser_start",
		"/parser_stop",
		"/parser_status",
		"/parser_auto on|off",
		"/parser_categories",
		"/parser_categories set women,men",
		"/proxy_set proxy1 proxy2 ...",
		"/proxy_clear",
		"",
		"<b>API Parsers</b>",
		"/api_list",
		"/api_enable parser_id on|off",
		"/api_set parser_id field value",
		func() string {
			if !isAdmin {
				return ""
			}
			return "\n<b>Admin</b>\n/grant user_id\n/revoke user_id\n/access_list"
		}(),
	}, "\n")
}

func (s *Service) cmdWhoAmI(chatID, userID int64, hasAccess, isAdmin bool) {
	_ = s.reply(chatID, fmt.Sprintf("Telegram ID: <code>%d</code>\naccess=%t\nadmin=%t", userID, hasAccess, isAdmin))
}

func (s *Service) cmdGrant(chatID int64, isAdmin bool, args string) {
	if !isAdmin {
		_ = s.reply(chatID, "Only admin can grant access.")
		return
	}
	targetID, err := strconv.ParseInt(strings.TrimSpace(args), 10, 64)
	if err != nil || targetID <= 0 {
		_ = s.reply(chatID, "Usage: /grant user_id")
		return
	}
	if err := s.acl.Grant(targetID); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("grant error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, fmt.Sprintf("Access granted for <code>%d</code>.", targetID))
}

func (s *Service) cmdRevoke(chatID int64, isAdmin bool, args string) {
	if !isAdmin {
		_ = s.reply(chatID, "Only admin can revoke access.")
		return
	}
	targetID, err := strconv.ParseInt(strings.TrimSpace(args), 10, 64)
	if err != nil || targetID <= 0 {
		_ = s.reply(chatID, "Usage: /revoke user_id")
		return
	}
	if err := s.acl.Revoke(targetID); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("revoke error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, fmt.Sprintf("Access revoked for <code>%d</code>.", targetID))
}

func (s *Service) cmdAccessList(chatID int64, isAdmin bool) {
	if !isAdmin {
		_ = s.reply(chatID, "Only admin can view access list.")
		return
	}
	ids := s.acl.ListAll()
	if len(ids) == 0 {
		_ = s.reply(chatID, "Access list is empty.")
		return
	}
	lines := []string{"<b>Allowed IDs</b>"}
	for _, id := range ids {
		lines = append(lines, fmt.Sprintf("- <code>%d</code>", id))
	}
	_ = s.reply(chatID, strings.Join(lines, "\n"))
}

func (s *Service) reply(chatID int64, text string) error {
	return s.tg.SendMessage(chatID, text)
}

func (s *Service) cmdAccounts(chatID int64, userID string) {
	accounts, err := s.store.LoadAccounts(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load accounts error: %s", html.EscapeString(err.Error())))
		return
	}
	if len(accounts) == 0 {
		_ = s.reply(chatID, "No accounts yet. Use /account_add.")
		return
	}
	lines := []string{"<b>Accounts</b>"}
	for _, acc := range accounts {
		limit := "inf"
		if acc.SendLimit > 0 {
			limit = strconv.Itoa(acc.SendLimit)
		}
		state := "off"
		if acc.Enabled {
			state = "on"
		}
		lines = append(lines, fmt.Sprintf("- <code>%s</code> [%s] sent=%d err=%d limit=%s",
			html.EscapeString(acc.Email), state, acc.SentCount, acc.ErrorCount, limit))
	}
	_ = s.reply(chatID, strings.Join(lines, "\n"))
}

func (s *Service) cmdAccountAdd(chatID int64, userID, args string) {
	parts := strings.Fields(args)
	if len(parts) < 2 {
		_ = s.reply(chatID, "Usage: /account_add email password")
		return
	}
	email := strings.ToLower(strings.TrimSpace(parts[0]))
	password := strings.TrimSpace(parts[1])

	accounts, err := s.store.LoadAccounts(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load accounts error: %s", html.EscapeString(err.Error())))
		return
	}
	for _, acc := range accounts {
		if strings.EqualFold(acc.Email, email) {
			_ = s.reply(chatID, "Account already exists.")
			return
		}
	}

	accounts = append(accounts, domain.Account{
		Email:      email,
		Password:   password,
		Enabled:    true,
		SendLimit:  0,
		SentCount:  0,
		ErrorCount: 0,
		LastError:  "",
	})
	if err := s.store.SaveAccounts(userID, accounts); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save accounts error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, "Account added.")
}

func (s *Service) cmdAccountToggle(chatID int64, userID, args string) {
	email := strings.ToLower(strings.TrimSpace(args))
	if email == "" {
		_ = s.reply(chatID, "Usage: /account_toggle email")
		return
	}
	accounts, err := s.store.LoadAccounts(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load accounts error: %s", html.EscapeString(err.Error())))
		return
	}
	for i := range accounts {
		if strings.EqualFold(accounts[i].Email, email) {
			accounts[i].Enabled = !accounts[i].Enabled
			if err := s.store.SaveAccounts(userID, accounts); err != nil {
				_ = s.reply(chatID, fmt.Sprintf("save accounts error: %s", html.EscapeString(err.Error())))
				return
			}
			state := "disabled"
			if accounts[i].Enabled {
				state = "enabled"
			}
			_ = s.reply(chatID, fmt.Sprintf("Account %s.", state))
			return
		}
	}
	_ = s.reply(chatID, "Account not found.")
}

func (s *Service) cmdAccountLimit(chatID int64, userID, args string) {
	parts := strings.Fields(args)
	if len(parts) != 2 {
		_ = s.reply(chatID, "Usage: /account_limit email limit")
		return
	}
	email := strings.ToLower(parts[0])
	limit, err := strconv.Atoi(parts[1])
	if err != nil || limit < 0 {
		_ = s.reply(chatID, "Limit must be a number >= 0.")
		return
	}

	accounts, err := s.store.LoadAccounts(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load accounts error: %s", html.EscapeString(err.Error())))
		return
	}
	for i := range accounts {
		if strings.EqualFold(accounts[i].Email, email) {
			accounts[i].SendLimit = limit
			if err := s.store.SaveAccounts(userID, accounts); err != nil {
				_ = s.reply(chatID, fmt.Sprintf("save accounts error: %s", html.EscapeString(err.Error())))
				return
			}
			_ = s.reply(chatID, "Limit updated.")
			return
		}
	}
	_ = s.reply(chatID, "Account not found.")
}

func (s *Service) cmdAccountDelete(chatID int64, userID, args string) {
	email := strings.ToLower(strings.TrimSpace(args))
	if email == "" {
		_ = s.reply(chatID, "Usage: /account_delete email")
		return
	}
	accounts, err := s.store.LoadAccounts(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load accounts error: %s", html.EscapeString(err.Error())))
		return
	}
	out := make([]domain.Account, 0, len(accounts))
	removed := false
	for _, acc := range accounts {
		if strings.EqualFold(acc.Email, email) {
			removed = true
			continue
		}
		out = append(out, acc)
	}
	if !removed {
		_ = s.reply(chatID, "Account not found.")
		return
	}
	if err := s.store.SaveAccounts(userID, out); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save accounts error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, "Account deleted.")
}

func (s *Service) cmdVars(chatID int64, userID string) {
	vars, err := s.store.LoadVariables(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load variables error: %s", html.EscapeString(err.Error())))
		return
	}
	keys := []string{"sender", "title", "text", "button", "link"}
	lines := []string{"<b>Variables</b>"}
	for _, key := range keys {
		lines = append(lines, fmt.Sprintf("- <code>%s</code>: %d", key, len(vars[key])))
	}
	_ = s.reply(chatID, strings.Join(lines, "\n"))
}

func (s *Service) cmdVarSet(chatID int64, userID, args string) {
	parts := strings.SplitN(args, " ", 2)
	if len(parts) != 2 {
		_ = s.reply(chatID, "Usage: /var_set key value1 | value2")
		return
	}
	key := strings.ToLower(strings.TrimSpace(parts[0]))
	if key != "sender" && key != "title" && key != "text" && key != "button" && key != "link" {
		_ = s.reply(chatID, "Key must be one of: sender,title,text,button,link")
		return
	}
	values := splitList(parts[1])
	if len(values) == 0 {
		_ = s.reply(chatID, "No values provided.")
		return
	}
	vars, err := s.store.LoadVariables(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load variables error: %s", html.EscapeString(err.Error())))
		return
	}
	vars[key] = values
	if err := s.store.SaveVariables(userID, vars); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save variables error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, "Variable values updated.")
}

func (s *Service) cmdSubjects(chatID int64, userID string) {
	subjects, err := s.store.LoadSubjects(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load subjects error: %s", html.EscapeString(err.Error())))
		return
	}
	lines := []string{"<b>Subjects</b>"}
	for _, subj := range subjects {
		lines = append(lines, fmt.Sprintf("- %s", html.EscapeString(subj)))
	}
	_ = s.reply(chatID, strings.Join(lines, "\n"))
}

func (s *Service) cmdSubjectsSet(chatID int64, userID, args string) {
	subjects := splitList(args)
	if len(subjects) == 0 {
		_ = s.reply(chatID, "Usage: /subjects_set subj1 | subj2")
		return
	}
	if err := s.store.SaveSubjects(userID, subjects); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save subjects error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, "Subjects updated.")
}

func (s *Service) cmdTemplates(chatID int64, userID string) {
	templates, selected, err := s.store.LoadTemplates(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load templates error: %s", html.EscapeString(err.Error())))
		return
	}
	if len(templates) == 0 {
		_ = s.reply(chatID, "No templates yet.")
		return
	}
	lines := []string{"<b>Templates</b>"}
	for name := range templates {
		flag := " "
		if slices.Contains(selected, name) {
			flag = "*"
		}
		lines = append(lines, fmt.Sprintf("%s <code>%s</code>", flag, html.EscapeString(name)))
	}
	lines = append(lines, "", "* = selected")
	_ = s.reply(chatID, strings.Join(lines, "\n"))
}

func (s *Service) cmdTemplateSet(chatID int64, userID, args string) {
	parts := strings.SplitN(args, " ", 2)
	if len(parts) != 2 {
		_ = s.reply(chatID, "Usage: /template_set name <html>")
		return
	}
	name := strings.TrimSpace(parts[0])
	content := strings.TrimSpace(parts[1])
	if name == "" || content == "" {
		_ = s.reply(chatID, "Template name and html are required.")
		return
	}
	templates, selected, err := s.store.LoadTemplates(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load templates error: %s", html.EscapeString(err.Error())))
		return
	}
	templates[name] = content
	if err := s.store.SaveTemplates(userID, templates, selected); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save templates error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, "Template saved.")
}

func (s *Service) cmdTemplateSelect(chatID int64, userID, args string, selectIt bool) {
	name := strings.TrimSpace(args)
	if name == "" {
		_ = s.reply(chatID, "Usage: /template_select name")
		return
	}
	templates, selected, err := s.store.LoadTemplates(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load templates error: %s", html.EscapeString(err.Error())))
		return
	}
	if _, ok := templates[name]; !ok {
		_ = s.reply(chatID, "Template not found.")
		return
	}
	if selectIt {
		if !slices.Contains(selected, name) {
			selected = append(selected, name)
		}
	} else {
		next := make([]string, 0, len(selected))
		for _, cur := range selected {
			if cur != name {
				next = append(next, cur)
			}
		}
		selected = next
	}
	if err := s.store.SaveTemplates(userID, templates, selected); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save templates error: %s", html.EscapeString(err.Error())))
		return
	}
	if selectIt {
		_ = s.reply(chatID, "Template selected.")
		return
	}
	_ = s.reply(chatID, "Template unselected.")
}

func (s *Service) cmdTemplateDelete(chatID int64, userID, args string) {
	name := strings.TrimSpace(args)
	if name == "" {
		_ = s.reply(chatID, "Usage: /template_delete name")
		return
	}
	templates, selected, err := s.store.LoadTemplates(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load templates error: %s", html.EscapeString(err.Error())))
		return
	}
	if _, ok := templates[name]; !ok {
		_ = s.reply(chatID, "Template not found.")
		return
	}
	delete(templates, name)
	next := make([]string, 0, len(selected))
	for _, cur := range selected {
		if cur != name {
			next = append(next, cur)
		}
	}
	if err := s.store.SaveTemplates(userID, templates, next); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save templates error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, "Template deleted.")
}

func (s *Service) cmdDelay(chatID int64, userID, args string) {
	parts := strings.Fields(args)
	if len(parts) != 2 {
		_ = s.reply(chatID, "Usage: /delay min max")
		return
	}
	minVal, err1 := strconv.Atoi(parts[0])
	maxVal, err2 := strconv.Atoi(parts[1])
	if err1 != nil || err2 != nil || minVal < 0 || maxVal < 0 || minVal > maxVal {
		_ = s.reply(chatID, "Invalid range.")
		return
	}
	cfg, err := s.store.LoadParserConfig(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	cfg.DelayMin = minVal
	cfg.DelayMax = maxVal
	if err := s.store.SaveParserConfig(userID, cfg); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, "Delay range updated.")
}

func (s *Service) cmdRotationSet(chatID int64, userID, args string) {
	parts := strings.Fields(args)
	if len(parts) != 2 {
		_ = s.reply(chatID, "Usage: /rotation_set key every")
		return
	}
	key := strings.ToLower(parts[0])
	if key != "sender" && key != "title" && key != "text" && key != "button" && key != "link" && key != "subject" {
		_ = s.reply(chatID, "Key must be sender|title|text|button|link|subject")
		return
	}
	every, err := strconv.Atoi(parts[1])
	if err != nil || every < 0 {
		_ = s.reply(chatID, "every must be a number >= 0")
		return
	}
	cfg, err := s.store.LoadParserConfig(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	if cfg.RotateEvery == nil {
		cfg.RotateEvery = map[string]int{}
	}
	cfg.RotateEvery[key] = every
	if err := s.store.SaveParserConfig(userID, cfg); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, "Rotation updated.")
}

func (s *Service) cmdSend(chatID int64, userID, args string) {
	recipients := extractEmails(args)
	if len(recipients) == 0 {
		_ = s.reply(chatID, "Usage: /send email1 email2 ...")
		return
	}

	userNumeric, _ := strconv.ParseInt(userID, 10, 64)
	s.mu.Lock()
	if _, exists := s.sends[userNumeric]; exists {
		s.mu.Unlock()
		_ = s.reply(chatID, "Campaign already running for this user. Use /send_stop.")
		return
	}
	sendCtx, cancel := context.WithCancel(context.Background())
	s.sends[userNumeric] = &sendSession{cancel: cancel}
	s.mu.Unlock()

	_ = s.reply(chatID, fmt.Sprintf("Campaign started for %d recipients.", len(recipients)))

	go func() {
		defer func() {
			s.mu.Lock()
			delete(s.sends, userNumeric)
			s.mu.Unlock()
		}()
		s.runCampaign(sendCtx, chatID, userID, recipients)
	}()
}

func (s *Service) cmdSendStop(chatID int64, userNumeric int64) {
	s.mu.Lock()
	session, ok := s.sends[userNumeric]
	s.mu.Unlock()
	if !ok {
		_ = s.reply(chatID, "Campaign is not running.")
		return
	}
	session.cancel()
	_ = s.reply(chatID, "Stopping campaign...")
}

func (s *Service) runCampaign(ctx context.Context, chatID int64, userID string, recipients []string) {
	accounts, err := s.store.LoadAccounts(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load accounts error: %s", html.EscapeString(err.Error())))
		return
	}
	vars, err := s.store.LoadVariables(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load variables error: %s", html.EscapeString(err.Error())))
		return
	}
	templates, selectedTemplates, err := s.store.LoadTemplates(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load templates error: %s", html.EscapeString(err.Error())))
		return
	}
	subjects, err := s.store.LoadSubjects(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load subjects error: %s", html.EscapeString(err.Error())))
		return
	}
	parserCfg, err := s.store.LoadParserConfig(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load parser config error: %s", html.EscapeString(err.Error())))
		return
	}

	enabledIndexes := make([]int, 0, len(accounts))
	for idx, acc := range accounts {
		if acc.Enabled {
			enabledIndexes = append(enabledIndexes, idx)
		}
	}

	if len(enabledIndexes) == 0 || len(selectedTemplates) == 0 {
		_ = s.reply(chatID, "Need at least one enabled account and one selected template.")
		return
	}

	okCount := 0
	errCount := 0
	rotationCounter := parserCfg.SendCounter
	accountPos := 0

	for i, recipient := range recipients {
		select {
		case <-ctx.Done():
			_ = s.reply(chatID, fmt.Sprintf("Campaign stopped. Sent=%d ok=%d failed=%d", okCount+errCount, okCount, errCount))
			parserCfg.SendCounter = rotationCounter
			_ = s.store.SaveParserConfig(userID, parserCfg)
			_ = s.store.SaveAccounts(userID, accounts)
			return
		default:
		}

		accountIdx := pickAccountIndex(accounts, enabledIndexes, accountPos)
		if accountIdx == -1 {
			_ = s.reply(chatID, "All enabled accounts reached send limits.")
			break
		}
		accountPos++
		acc := &accounts[accountIdx]

		templateName := selectedTemplates[rand.Intn(len(selectedTemplates))]
		htmlTemplate := templates[templateName]
		if strings.TrimSpace(htmlTemplate) == "" {
			errCount++
			acc.ErrorCount++
			acc.LastError = "empty template"
			continue
		}

		recipientForTemplate := recipient
		senderName := replaceRandomIDs(pickRotated(vars["sender"], "sender", rotationCounter, parserCfg.RotateEvery, ""))
		title := replaceRandomIDs(pickRotated(vars["title"], "title", rotationCounter, parserCfg.RotateEvery, ""))
		body := replaceRandomIDs(pickRotated(vars["text"], "text", rotationCounter, parserCfg.RotateEvery, ""))
		button := replaceRandomIDs(pickRotated(vars["button"], "button", rotationCounter, parserCfg.RotateEvery, ""))
		link := replaceRandomIDs(pickRotated(vars["link"], "link", rotationCounter, parserCfg.RotateEvery, ""))
		subjectTpl := pickRotated(subjects, "subject", rotationCounter, parserCfg.RotateEvery, "Hello from Poshmark")

		fixedID := randomID()
		subject := applyVars(subjectTpl, recipientForTemplate, senderName, title, body, button, link, fixedID)
		htmlBody := applyVars(htmlTemplate, recipientForTemplate, senderName, title, body, button, link, fixedID)

		sender := smtp.NewSender(acc.Email, acc.Password, s.cfg.SMTPMap, s.cfg.StartTLSOnly, s.cfg.SSLOnly)
		ok, status := sender.SendEmail(recipient, subject, htmlBody, senderName)

		if ok {
			okCount++
			acc.SentCount++
		} else {
			errCount++
			acc.ErrorCount++
			acc.LastError = trim(status, 140)
		}

		_ = s.store.AppendLog(userID, domain.SentLog{
			FromEmail: acc.Email,
			ToEmail:   recipient,
			Subject:   subject,
			Status: func() string {
				if ok {
					return "✅"
				}
				return "❌"
			}(),
			Timestamp: time.Now().Format(time.RFC3339),
			Error: func() string {
				if ok {
					return ""
				}
				return status
			}(),
		})

		icon := "✅"
		if !ok {
			icon = "❌"
		}
		_ = s.reply(chatID, fmt.Sprintf("%s [%d/%d] <code>%s</code> via <code>%s</code>",
			icon, i+1, len(recipients), html.EscapeString(recipient), html.EscapeString(acc.Email)))

		rotationCounter++

		if i < len(recipients)-1 {
			delaySec := randomDelay(parserCfg.DelayMin, parserCfg.DelayMax)
			select {
			case <-ctx.Done():
				_ = s.reply(chatID, fmt.Sprintf("Campaign stopped. Sent=%d ok=%d failed=%d", okCount+errCount, okCount, errCount))
				parserCfg.SendCounter = rotationCounter
				_ = s.store.SaveParserConfig(userID, parserCfg)
				_ = s.store.SaveAccounts(userID, accounts)
				return
			case <-time.After(time.Duration(delaySec) * time.Second):
			}
		}
	}

	parserCfg.SendCounter = rotationCounter
	_ = s.store.SaveParserConfig(userID, parserCfg)
	_ = s.store.SaveAccounts(userID, accounts)
	_ = s.reply(chatID, fmt.Sprintf("Campaign complete. Total=%d ok=%d failed=%d", okCount+errCount, okCount, errCount))
}

func (s *Service) cmdParserStart(ctx context.Context, chatID, userNumeric int64, userID string) {
	s.mu.Lock()
	if _, exists := s.parsers[userNumeric]; exists {
		s.mu.Unlock()
		_ = s.reply(chatID, "Parser already running.")
		return
	}
	s.mu.Unlock()

	cfg, err := s.store.LoadParserConfig(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load parser config error: %s", html.EscapeString(err.Error())))
		return
	}

	parserCtx, cancel := context.WithCancel(ctx)
	out := make(chan domain.PoshmarkItem, 256)
	p := parser.NewPoshmarkParser(cfg, func(msg string) {
		_ = s.reply(chatID, "parser: "+html.EscapeString(msg))
	})

	session := &parserSession{
		cancel:    cancel,
		parser:    p,
		startedAt: time.Now(),
		autoSend:  cfg.AutoSend,
	}

	s.mu.Lock()
	s.parsers[userNumeric] = session
	s.mu.Unlock()

	_ = s.reply(chatID, "Parser started.")

	go func() {
		p.Start(parserCtx, out)
		s.mu.Lock()
		delete(s.parsers, userNumeric)
		s.mu.Unlock()
	}()

	go s.consumeParsedItems(parserCtx, chatID, userID, userNumeric, out)
}

func (s *Service) consumeParsedItems(ctx context.Context, chatID int64, userID string, userNumeric int64, out <-chan domain.PoshmarkItem) {
	for {
		select {
		case <-ctx.Done():
			_ = s.reply(chatID, "Parser stopped.")
			return
		case item, ok := <-out:
			if !ok {
				_ = s.reply(chatID, "Parser finished.")
				return
			}

			text := fmt.Sprintf("Found: <code>%s</code> user=<code>%s</code> sales=%s",
				html.EscapeString(item.Email), html.EscapeString(item.Username), html.EscapeString(item.SoldCount))
			_ = s.reply(chatID, text)

			s.mu.Lock()
			session := s.parsers[userNumeric]
			auto := session != nil && session.autoSend
			s.mu.Unlock()

			if auto {
				s.sendToItem(chatID, userID, item)
			}
		}
	}
}

func (s *Service) sendToItem(chatID int64, userID string, item domain.PoshmarkItem) {
	accounts, err := s.store.LoadAccounts(userID)
	if err != nil {
		return
	}
	vars, err := s.store.LoadVariables(userID)
	if err != nil {
		return
	}
	templates, selected, err := s.store.LoadTemplates(userID)
	if err != nil {
		return
	}
	subjects, err := s.store.LoadSubjects(userID)
	if err != nil {
		return
	}
	cfg, err := s.store.LoadParserConfig(userID)
	if err != nil {
		return
	}
	if len(selected) == 0 {
		return
	}

	enabledIndexes := make([]int, 0, len(accounts))
	for idx := range accounts {
		if accounts[idx].Enabled && (accounts[idx].SendLimit <= 0 || accounts[idx].SentCount < accounts[idx].SendLimit) {
			enabledIndexes = append(enabledIndexes, idx)
		}
	}
	if len(enabledIndexes) == 0 {
		return
	}

	for _, accIdx := range enabledIndexes {
		acc := &accounts[accIdx]
		rotationCounter := cfg.SendCounter
		templateName := selected[rand.Intn(len(selected))]
		htmlTemplate := templates[templateName]
		if strings.TrimSpace(htmlTemplate) == "" {
			continue
		}

		senderName := replaceRandomIDs(pickRotated(vars["sender"], "sender", rotationCounter, cfg.RotateEvery, ""))
		title := replaceRandomIDs(pickRotated(vars["title"], "title", rotationCounter, cfg.RotateEvery, ""))
		body := replaceRandomIDs(pickRotated(vars["text"], "text", rotationCounter, cfg.RotateEvery, ""))
		button := replaceRandomIDs(pickRotated(vars["button"], "button", rotationCounter, cfg.RotateEvery, ""))
		link := replaceRandomIDs(pickRotated(vars["link"], "link", rotationCounter, cfg.RotateEvery, ""))
		subjectTpl := pickRotated(subjects, "subject", rotationCounter, cfg.RotateEvery, "Hello from Poshmark")
		fixedID := randomID()

		subject := applyVars(subjectTpl, item.Email, senderName, title, body, button, link, fixedID)
		htmlBody := applyVars(htmlTemplate, item.Email, senderName, title, body, button, link, fixedID)

		delaySec := randomDelay(cfg.DelayMin, cfg.DelayMax)
		time.Sleep(time.Duration(delaySec) * time.Second)

		sender := smtp.NewSender(acc.Email, acc.Password, s.cfg.SMTPMap, s.cfg.StartTLSOnly, s.cfg.SSLOnly)
		ok, status := sender.SendEmail(item.Email, subject, htmlBody, senderName)
		if ok {
			acc.SentCount++
		} else {
			acc.ErrorCount++
			acc.LastError = trim(status, 140)
		}
		cfg.SendCounter++
		_ = s.store.AppendLog(userID, domain.SentLog{
			FromEmail: acc.Email,
			ToEmail:   item.Email,
			Subject:   subject,
			Status: func() string {
				if ok {
					return "✅"
				}
				return "❌"
			}(),
			Timestamp: time.Now().Format(time.RFC3339),
			Error: func() string {
				if ok {
					return ""
				}
				return status
			}(),
		})

		icon := "✅"
		if !ok {
			icon = "❌"
		}
		_ = s.reply(chatID, fmt.Sprintf("%s auto-send %s -> %s", icon, html.EscapeString(acc.Email), html.EscapeString(item.Email)))
	}

	_ = s.store.SaveParserConfig(userID, cfg)
	_ = s.store.SaveAccounts(userID, accounts)
}

func (s *Service) cmdParserStop(chatID, userNumeric int64) {
	s.mu.Lock()
	session, ok := s.parsers[userNumeric]
	s.mu.Unlock()
	if !ok {
		_ = s.reply(chatID, "Parser is not running.")
		return
	}
	session.cancel()
	_ = s.reply(chatID, "Stopping parser...")
}

func (s *Service) cmdParserStatus(chatID, userNumeric int64) {
	s.mu.Lock()
	session, ok := s.parsers[userNumeric]
	s.mu.Unlock()
	if !ok {
		_ = s.reply(chatID, "Parser is not running.")
		return
	}
	stats := session.parser.Stats()
	uptime := time.Since(session.startedAt).Round(time.Second)
	_ = s.reply(chatID, fmt.Sprintf("Parser running %s. found=%d valid=%d errors=%d auto_send=%t",
		uptime, stats["found"], stats["valid"], stats["errors"], session.autoSend))
}

func (s *Service) cmdParserAuto(chatID, userNumeric int64, userID, args string) {
	val := strings.ToLower(strings.TrimSpace(args))
	if val != "on" && val != "off" {
		_ = s.reply(chatID, "Usage: /parser_auto on|off")
		return
	}
	cfg, err := s.store.LoadParserConfig(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	cfg.AutoSend = val == "on"
	if err := s.store.SaveParserConfig(userID, cfg); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	s.mu.Lock()
	if session, ok := s.parsers[userNumeric]; ok {
		session.autoSend = cfg.AutoSend
	}
	s.mu.Unlock()
	_ = s.reply(chatID, fmt.Sprintf("parser auto_send=%t", cfg.AutoSend))
}

func (s *Service) cmdParserCategories(chatID int64, userID, args string) {
	cfg, err := s.store.LoadParserConfig(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	args = strings.TrimSpace(args)
	if args == "" {
		lines := []string{"<b>Parser categories</b>", "selected:"}
		for _, cat := range cfg.SelectedCategories {
			lines = append(lines, "- <code>"+html.EscapeString(cat)+"</code>")
		}
		lines = append(lines, "", "available aliases:")
		for alias, path := range s.cfg.PoshmarkCategory {
			lines = append(lines, fmt.Sprintf("- %s => %s", html.EscapeString(alias), html.EscapeString(path)))
		}
		_ = s.reply(chatID, strings.Join(lines, "\n"))
		return
	}
	if !strings.HasPrefix(strings.ToLower(args), "set ") {
		_ = s.reply(chatID, "Usage: /parser_categories OR /parser_categories set women,men")
		return
	}
	rawList := strings.TrimSpace(strings.TrimPrefix(strings.ToLower(args), "set"))
	names := strings.Split(rawList, ",")
	selected := make([]string, 0, len(names))
	for _, name := range names {
		alias := strings.TrimSpace(name)
		if alias == "" {
			continue
		}
		path, ok := s.cfg.PoshmarkCategory[alias]
		if ok {
			selected = append(selected, path)
		}
	}
	if len(selected) == 0 {
		_ = s.reply(chatID, "No valid categories selected.")
		return
	}
	cfg.SelectedCategories = selected
	if err := s.store.SaveParserConfig(userID, cfg); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, "Parser categories updated.")
}

func (s *Service) cmdProxySet(chatID int64, userID, args string) {
	proxies := splitList(args)
	if len(proxies) == 0 {
		_ = s.reply(chatID, "Usage: /proxy_set proxy1 proxy2 ...")
		return
	}
	cfg, err := s.store.LoadParserConfig(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	cfg.Proxies = proxies
	cfg.ProxyIdx = 0
	if err := s.store.SaveParserConfig(userID, cfg); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, fmt.Sprintf("Saved %d proxies.", len(proxies)))
}

func (s *Service) cmdProxyClear(chatID int64, userID string) {
	cfg, err := s.store.LoadParserConfig(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	cfg.Proxies = []string{}
	cfg.ProxyIdx = 0
	if err := s.store.SaveParserConfig(userID, cfg); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, "Proxies cleared.")
}

func (s *Service) cmdAPIList(chatID int64, userID string) {
	cfg, err := s.store.LoadAPIParsersConfig(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load api parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	lines := []string{"<b>API Parsers</b>"}
	for id, parserCfg := range cfg {
		lines = append(lines, fmt.Sprintf("- <code>%s</code> enabled=%t platform=%s country=%s limit=%d",
			html.EscapeString(id), parserCfg.Enabled, html.EscapeString(parserCfg.Platform),
			html.EscapeString(parserCfg.Country), parserCfg.Limit))
	}
	_ = s.reply(chatID, strings.Join(lines, "\n"))
}

func (s *Service) cmdAPIEnable(chatID int64, userID, args string) {
	parts := strings.Fields(args)
	if len(parts) != 2 {
		_ = s.reply(chatID, "Usage: /api_enable parser_id on|off")
		return
	}
	id := strings.TrimSpace(parts[0])
	onOff := strings.ToLower(strings.TrimSpace(parts[1]))
	if onOff != "on" && onOff != "off" {
		_ = s.reply(chatID, "Second argument must be on or off.")
		return
	}
	cfg, err := s.store.LoadAPIParsersConfig(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load api parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	item, ok := cfg[id]
	if !ok {
		_ = s.reply(chatID, "Parser ID not found.")
		return
	}
	item.Enabled = onOff == "on"
	cfg[id] = item
	if err := s.store.SaveAPIParsersConfig(userID, cfg); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save api parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, "API parser enabled flag updated.")
}

func (s *Service) cmdAPISet(chatID int64, userID, args string) {
	parts := strings.Fields(args)
	if len(parts) < 3 {
		_ = s.reply(chatID, "Usage: /api_set parser_id field value")
		return
	}
	id := strings.TrimSpace(parts[0])
	field := strings.ToLower(strings.TrimSpace(parts[1]))
	value := strings.TrimSpace(strings.Join(parts[2:], " "))

	cfg, err := s.store.LoadAPIParsersConfig(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load api parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	item, ok := cfg[id]
	if !ok {
		_ = s.reply(chatID, "Parser ID not found.")
		return
	}

	switch field {
	case "token":
		item.Token = value
	case "platform":
		item.Platform = value
	case "country":
		item.Country = value
	case "category":
		item.Category = value
	case "price":
		item.Price = value
	case "limit":
		n, convErr := strconv.Atoi(value)
		if convErr != nil {
			_ = s.reply(chatID, "limit must be integer")
			return
		}
		item.Limit = n
	case "interval":
		n, convErr := strconv.Atoi(value)
		if convErr != nil {
			_ = s.reply(chatID, "interval must be integer")
			return
		}
		item.Interval = n
	case "publication":
		item.Publication = value
	case "reviews":
		item.Reviews = value
	case "ads":
		item.Ads = value
	case "sells":
		item.Sells = value
	case "buys":
		item.Buys = value
	case "blacklist":
		item.Blacklist = value
	case "email_only":
		item.EmailOnly = parseBool(value)
	case "auto_send":
		item.AutoSend = parseBool(value)
	default:
		_ = s.reply(chatID, "Unsupported field.")
		return
	}

	cfg[id] = item
	if err := s.store.SaveAPIParsersConfig(userID, cfg); err != nil {
		_ = s.reply(chatID, fmt.Sprintf("save api parser config error: %s", html.EscapeString(err.Error())))
		return
	}
	_ = s.reply(chatID, "API parser field updated.")
}

func (s *Service) cmdLogs(chatID int64, userID string) {
	logs, err := s.store.LoadLogs(userID)
	if err != nil {
		_ = s.reply(chatID, fmt.Sprintf("load logs error: %s", html.EscapeString(err.Error())))
		return
	}
	if len(logs) == 0 {
		_ = s.reply(chatID, "No logs yet.")
		return
	}
	start := 0
	if len(logs) > 10 {
		start = len(logs) - 10
	}
	lines := []string{"<b>Last logs</b>"}
	for _, entry := range logs[start:] {
		lines = append(lines, fmt.Sprintf("%s <code>%s</code> -> <code>%s</code> %s",
			html.EscapeString(entry.Status),
			html.EscapeString(entry.FromEmail),
			html.EscapeString(entry.ToEmail),
			html.EscapeString(trim(entry.Error, 80)),
		))
	}
	_ = s.reply(chatID, strings.Join(lines, "\n"))
}

func splitList(raw string) []string {
	parts := strings.FieldsFunc(raw, func(r rune) bool {
		return r == '\n' || r == '|' || r == ',' || r == ';'
	})
	seen := map[string]struct{}{}
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		item := strings.TrimSpace(p)
		if item == "" {
			continue
		}
		if _, ok := seen[item]; ok {
			continue
		}
		seen[item] = struct{}{}
		out = append(out, item)
	}
	return out
}

func extractEmails(raw string) []string {
	found := emailPattern.FindAllString(strings.ToLower(raw), -1)
	seen := map[string]struct{}{}
	out := make([]string, 0, len(found))
	for _, email := range found {
		if _, ok := seen[email]; ok {
			continue
		}
		seen[email] = struct{}{}
		out = append(out, email)
	}
	return out
}

func pickAccountIndex(accounts []domain.Account, enabledIndexes []int, pos int) int {
	if len(enabledIndexes) == 0 {
		return -1
	}
	for i := 0; i < len(enabledIndexes); i++ {
		idx := enabledIndexes[(pos+i)%len(enabledIndexes)]
		acc := accounts[idx]
		if acc.SendLimit > 0 && acc.SentCount >= acc.SendLimit {
			continue
		}
		return idx
	}
	return -1
}

func randomID() string {
	min := int64(1000000000)
	max := int64(9999999999)
	return strconv.FormatInt(min+rand.Int63n(max-min+1), 10)
}

func replaceRandomIDs(text string) string {
	for strings.Contains(text, "{randomID}") {
		text = strings.Replace(text, "{randomID}", randomID(), 1)
	}
	return text
}

func applyVars(text, recipient, sender, title, body, button, link, fixedID string) string {
	repl := []struct {
		old string
		new string
	}{
		{"{recipient}", recipient},
		{"{sender}", sender},
		{"{title}", title},
		{"{text}", body},
		{"{button}", button},
		{"{link}", link},
	}
	for _, pair := range repl {
		text = strings.ReplaceAll(text, pair.old, pair.new)
	}
	for strings.Contains(text, "{randomID}") {
		text = strings.Replace(text, "{randomID}", fixedID, 1)
	}
	return text
}

func pickRotated(values []string, key string, counter int, rotateEvery map[string]int, defaultValue string) string {
	if len(values) == 0 {
		return defaultValue
	}
	every := 0
	if rotateEvery != nil {
		every = rotateEvery[key]
	}
	if every <= 0 {
		return values[rand.Intn(len(values))]
	}
	idx := (counter / every) % len(values)
	return values[idx]
}

func randomDelay(minVal, maxVal int) int {
	if minVal < 0 {
		minVal = 0
	}
	if maxVal < minVal {
		maxVal = minVal
	}
	if minVal == maxVal {
		return minVal
	}
	return minVal + rand.Intn(maxVal-minVal+1)
}

func parseBool(raw string) bool {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "1", "true", "yes", "on", "y":
		return true
	default:
		return false
	}
}

func trim(value string, max int) string {
	if max <= 0 || len(value) <= max {
		return value
	}
	return value[:max]
}
