package storage

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"

	"poshmark/internal/config"
	"poshmark/internal/domain"
)

type JSONStore struct {
	baseDir    string
	categories []string
	apiParsers []string
	mu         sync.Mutex
}

func NewJSONStore(cfg config.AppConfig) *JSONStore {
	categories := make([]string, 0, len(cfg.PoshmarkCategory))
	for _, category := range cfg.PoshmarkCategory {
		categories = append(categories, category)
	}

	apiParsers := make([]string, 0, len(cfg.APIParsers))
	for parserID := range cfg.APIParsers {
		apiParsers = append(apiParsers, parserID)
	}

	return &JSONStore{
		baseDir:    cfg.DataDir,
		categories: categories,
		apiParsers: apiParsers,
	}
}

func (s *JSONStore) userPath(userID, filename string) (string, error) {
	userDir := filepath.Join(s.baseDir, userID)
	if err := os.MkdirAll(userDir, 0o755); err != nil {
		return "", err
	}
	return filepath.Join(userDir, filename), nil
}

func (s *JSONStore) readJSON(path string, out any) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return os.ErrNotExist
		}
		return err
	}
	return json.Unmarshal(raw, out)
}

func (s *JSONStore) writeJSON(path string, value any) error {
	raw, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, raw, 0o644)
}

func (s *JSONStore) LoadAccounts(userID string) ([]domain.Account, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "accounts.json")
	if err != nil {
		return nil, err
	}

	accounts := []domain.Account{}
	if err := s.readJSON(path, &accounts); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return accounts, nil
		}
		return nil, err
	}

	return accounts, nil
}

func (s *JSONStore) SaveAccounts(userID string, accounts []domain.Account) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "accounts.json")
	if err != nil {
		return err
	}
	return s.writeJSON(path, accounts)
}

func (s *JSONStore) LoadVariables(userID string) (map[string][]string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	defaults := map[string][]string{
		"sender": {},
		"title":  {},
		"text":   {},
		"button": {},
		"link":   {},
	}

	path, err := s.userPath(userID, "variables.json")
	if err != nil {
		return nil, err
	}

	if err := s.readJSON(path, &defaults); err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}

	return defaults, nil
}

func (s *JSONStore) SaveVariables(userID string, variables map[string][]string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "variables.json")
	if err != nil {
		return err
	}
	return s.writeJSON(path, variables)
}

func (s *JSONStore) LoadTemplates(userID string) (map[string]string, []string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "templates.json")
	if err != nil {
		return nil, nil, err
	}

	type payload struct {
		Templates map[string]string `json:"templates"`
		Selected  []string          `json:"selected"`
	}

	data := payload{
		Templates: map[string]string{},
		Selected:  []string{},
	}

	if err := s.readJSON(path, &data); err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, nil, err
	}

	return data.Templates, data.Selected, nil
}

func (s *JSONStore) SaveTemplates(userID string, templates map[string]string, selected []string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "templates.json")
	if err != nil {
		return err
	}

	data := struct {
		Templates map[string]string `json:"templates"`
		Selected  []string          `json:"selected"`
	}{
		Templates: templates,
		Selected:  selected,
	}

	return s.writeJSON(path, data)
}

func (s *JSONStore) LoadSubjects(userID string) ([]string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "subjects.json")
	if err != nil {
		return nil, err
	}

	var subjects []string
	if err := s.readJSON(path, &subjects); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return []string{"Hello"}, nil
		}
		return nil, err
	}
	if len(subjects) == 0 {
		return []string{"Hello"}, nil
	}

	return subjects, nil
}

func (s *JSONStore) SaveSubjects(userID string, subjects []string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "subjects.json")
	if err != nil {
		return err
	}
	return s.writeJSON(path, subjects)
}

func (s *JSONStore) LoadLogs(userID string) ([]domain.SentLog, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "logs.json")
	if err != nil {
		return nil, err
	}

	logs := []domain.SentLog{}
	if err := s.readJSON(path, &logs); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return logs, nil
		}
		return nil, err
	}

	return logs, nil
}

func (s *JSONStore) AppendLog(userID string, log domain.SentLog) error {
	logs, err := s.LoadLogs(userID)
	if err != nil {
		return err
	}

	logs = append(logs, log)
	if len(logs) > 1000 {
		logs = logs[len(logs)-1000:]
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "logs.json")
	if err != nil {
		return err
	}
	return s.writeJSON(path, logs)
}

func (s *JSONStore) LoadAPIParsersConfig(userID string) (map[string]domain.APIParserSettings, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "api_parsers.json")
	if err != nil {
		return nil, err
	}

	settings := map[string]domain.APIParserSettings{}
	for _, parserID := range s.apiParsers {
		settings[parserID] = domain.DefaultAPIParserSettings()
	}

	saved := map[string]domain.APIParserSettings{}
	if err := s.readJSON(path, &saved); err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}

	for parserID, cfg := range saved {
		settings[parserID] = cfg
	}

	return settings, nil
}

func (s *JSONStore) SaveAPIParsersConfig(userID string, cfg map[string]domain.APIParserSettings) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "api_parsers.json")
	if err != nil {
		return err
	}
	return s.writeJSON(path, cfg)
}

func (s *JSONStore) LoadParserConfig(userID string) (domain.ParserConfig, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "parser.json")
	if err != nil {
		return domain.ParserConfig{}, err
	}

	cfg := domain.DefaultParserConfig(s.categories)
	if err := s.readJSON(path, &cfg); err != nil && !errors.Is(err, os.ErrNotExist) {
		return domain.ParserConfig{}, err
	}
	if cfg.RotateEvery == nil {
		cfg.RotateEvery = domain.DefaultParserConfig(s.categories).RotateEvery
	}
	return cfg, nil
}

func (s *JSONStore) SaveParserConfig(userID string, cfg domain.ParserConfig) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	path, err := s.userPath(userID, "parser.json")
	if err != nil {
		return err
	}
	return s.writeJSON(path, cfg)
}
