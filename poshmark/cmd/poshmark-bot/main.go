package main

import (
	"context"
	"log"
	"os/signal"
	"syscall"

	"poshmark/internal/bot"
	"poshmark/internal/config"
)

func main() {
	cfg := config.Load()
	if cfg.BotToken == "" {
		log.Fatal("BOT_TOKEN is required")
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	service, err := bot.NewService(cfg)
	if err != nil {
		log.Fatalf("init bot service: %v", err)
	}
	log.Printf("telegram bot started. data_dir=%s", cfg.DataDir)
	if err := service.Run(ctx); err != nil {
		log.Fatalf("bot stopped with error: %v", err)
	}
}
