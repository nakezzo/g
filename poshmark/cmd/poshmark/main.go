package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"poshmark/internal/config"
	"poshmark/internal/domain"
	"poshmark/internal/parser"
	"poshmark/internal/storage"
)

func main() {
	cfg := config.Load()
	store := storage.NewJSONStore(cfg)

	userID := os.Getenv("USER_ID")
	if userID == "" {
		userID = "demo"
	}

	parserCfg, err := store.LoadParserConfig(userID)
	if err != nil {
		log.Fatalf("load parser config: %v", err)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	out := make(chan domain.PoshmarkItem, 256)
	p := parser.NewPoshmarkParser(parserCfg, func(message string) {
		log.Println("[parser]", message)
	})

	log.Printf("Go service started. data_dir=%s user_id=%s", cfg.DataDir, userID)
	go p.Start(ctx, out)

	for {
		select {
		case <-ctx.Done():
			log.Println("shutdown signal received")
			time.Sleep(200 * time.Millisecond)
			return
		case item, ok := <-out:
			if !ok {
				log.Println("parser stopped")
				return
			}
			log.Printf("item: user=%s email=%s title=%q", item.Username, item.Email, item.ItemTitle)
		}
	}
}
