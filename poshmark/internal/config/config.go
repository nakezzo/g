package config

import (
	"os"
	"strconv"
	"strings"
)

type APIParserInfo struct {
	Name string `json:"name"`
	Base string `json:"base"`
	Docs string `json:"docs"`
	Icon string `json:"icon"`
	Auth string `json:"auth"`
}

type AppConfig struct {
	BotToken         string
	BotAdminIDs      []int64
	DataDir          string
	SMTPMap          map[string]string
	PoshmarkCategory map[string]string
	VVSPlatforms     []string
	APIParsers       map[string]APIParserInfo
	StartTLSOnly     map[string]struct{}
	SSLOnly          map[string]struct{}
}

func Load() AppConfig {
	dataDir := os.Getenv("DATA_DIR")
	if dataDir == "" {
		dataDir = "userdata"
	}
	adminIDs := parseAdminIDs(os.Getenv("BOT_ADMIN_IDS"))

	return AppConfig{
		BotToken:    os.Getenv("BOT_TOKEN"),
		BotAdminIDs: adminIDs,
		DataDir:     dataDir,
		SMTPMap: map[string]string{
			"seznam.cz": "smtp.seznam.cz",
			"email.cz":  "smtp.seznam.cz",
			"post.cz":   "smtp.seznam.cz",
		},
		PoshmarkCategory: map[string]string{
			"women":       "/category/Women",
			"men":         "/category/Men",
			"kids":        "/category/Kids",
			"home":        "/category/Home",
			"pets":        "/category/Pets",
			"electronics": "/category/Electronics",
		},
		VVSPlatforms: []string{
			"vinted", "poshmark", "etsy", "depop", "grailed", "gumtree", "mercari",
			"offerup", "kijiji", "kleinanzeigen", "marktplaats", "leboncoin", "olx",
			"wallapop", "subito", "ricardo", "finn", "tori", "dba", "2dehands",
			"jofogas", "bazaraki", "adverts", "tise", "skelbiu", "beebs", "milanuncios",
			"marko", "fiverr", "quoka", "laendleanzeiger",
		},
		APIParsers: map[string]APIParserInfo{
			"vvs": {
				Name: "VVS Project",
				Base: "https://vvs.cx",
				Docs: "https://telegra.ph/Dokumentaciya-API-03-18",
				Icon: "🔵",
				Auth: "api-key header",
			},
			"storm": {
				Name: "Storm Parser",
				Base: "https://stormparser.lol",
				Docs: "https://stormparser.lol/docs",
				Icon: "⚡",
				Auth: "Bearer token",
			},
			"xproject": {
				Name: "xProject",
				Base: "https://api.xproject.icu",
				Docs: "https://api.xproject.icu/api/docs",
				Icon: "🔴",
				Auth: "X-API-Key header",
			},
		},
		StartTLSOnly: map[string]struct{}{
			"smtp-mail.outlook.com": {},
			"smtp.office365.com":    {},
			"smtp.mail.me.com":      {},
		},
		SSLOnly: map[string]struct{}{},
	}
}

func parseAdminIDs(raw string) []int64 {
	if strings.TrimSpace(raw) == "" {
		return []int64{}
	}
	parts := strings.Split(raw, ",")
	out := make([]int64, 0, len(parts))
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		id, err := strconv.ParseInt(part, 10, 64)
		if err != nil {
			continue
		}
		out = append(out, id)
	}
	return out
}
