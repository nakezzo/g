package access

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"sync"
)

type ACL struct {
	path    string
	admins  map[int64]struct{}
	allowed map[int64]struct{}
	mu      sync.Mutex
}

type aclPayload struct {
	AllowedIDs []int64 `json:"allowed_ids"`
}

func NewACL(dataDir string, adminIDs []int64) (*ACL, error) {
	if err := os.MkdirAll(dataDir, 0o755); err != nil {
		return nil, err
	}

	acl := &ACL{
		path:    filepath.Join(dataDir, "access.json"),
		admins:  map[int64]struct{}{},
		allowed: map[int64]struct{}{},
	}

	for _, id := range adminIDs {
		acl.admins[id] = struct{}{}
	}

	if err := acl.load(); err != nil {
		return nil, err
	}
	return acl, nil
}

func (a *ACL) load() error {
	raw, err := os.ReadFile(a.path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return err
	}

	var payload aclPayload
	if err := json.Unmarshal(raw, &payload); err != nil {
		return err
	}
	for _, id := range payload.AllowedIDs {
		a.allowed[id] = struct{}{}
	}
	return nil
}

func (a *ACL) saveLocked() error {
	ids := make([]int64, 0, len(a.allowed))
	for id := range a.allowed {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })

	raw, err := json.MarshalIndent(aclPayload{AllowedIDs: ids}, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(a.path, raw, 0o644)
}

func (a *ACL) IsAdmin(userID int64) bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	_, ok := a.admins[userID]
	return ok
}

func (a *ACL) HasAccess(userID int64) bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	if _, ok := a.admins[userID]; ok {
		return true
	}
	_, ok := a.allowed[userID]
	return ok
}

func (a *ACL) Grant(userID int64) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.allowed[userID] = struct{}{}
	return a.saveLocked()
}

func (a *ACL) Revoke(userID int64) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	delete(a.allowed, userID)
	return a.saveLocked()
}

func (a *ACL) ListAll() []int64 {
	a.mu.Lock()
	defer a.mu.Unlock()

	ids := make([]int64, 0, len(a.allowed)+len(a.admins))
	for id := range a.allowed {
		ids = append(ids, id)
	}
	for id := range a.admins {
		if !slices.Contains(ids, id) {
			ids = append(ids, id)
		}
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	return ids
}
