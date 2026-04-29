package smtp

import (
	"crypto/tls"
	"fmt"
	"net"
	"net/mail"
	"net/smtp"
	"strings"
	"time"
)

type Sender struct {
	email        string
	password     string
	server       string
	startTLSOnly map[string]struct{}
	sslOnly      map[string]struct{}
}

func NewSender(email, password string, smtpMap map[string]string, startTLSOnly, sslOnly map[string]struct{}) *Sender {
	return &Sender{
		email:        email,
		password:     password,
		server:       GetSMTPServer(email, smtpMap),
		startTLSOnly: startTLSOnly,
		sslOnly:      sslOnly,
	}
}

func GetSMTPServer(email string, smtpMap map[string]string) string {
	parts := strings.Split(email, "@")
	if len(parts) != 2 {
		return ""
	}
	domain := strings.ToLower(parts[1])
	if server, ok := smtpMap[domain]; ok {
		return server
	}
	return "smtp." + domain
}

func (s *Sender) makeMessage(toEmail, subject, htmlContent, senderName string) []byte {
	from := s.email
	if senderName != "" {
		from = (&mail.Address{Name: senderName, Address: s.email}).String()
	}
	body := strings.Join([]string{
		"From: " + from,
		"To: " + toEmail,
		"Subject: " + subject,
		"MIME-Version: 1.0",
		"Content-Type: text/html; charset=UTF-8",
		"",
		htmlContent,
	}, "\r\n")
	return []byte(body)
}

func (s *Sender) auth() smtp.Auth {
	return smtp.PlainAuth("", s.email, s.password, s.server)
}

func (s *Sender) trySSL(msg []byte, toEmail string) (bool, string) {
	conn, err := tls.DialWithDialer(&net.Dialer{Timeout: 30 * time.Second}, "tcp", s.server+":465", &tls.Config{
		ServerName: s.server,
		MinVersion: tls.VersionTLS12,
	})
	if err != nil {
		return false, fmt.Sprintf("SSL/465 dial error: %v", err)
	}
	defer conn.Close()

	client, err := smtp.NewClient(conn, s.server)
	if err != nil {
		return false, fmt.Sprintf("SSL/465 client error: %v", err)
	}
	defer client.Close()

	if err = client.Auth(s.auth()); err != nil {
		return false, fmt.Sprintf("SSL/465 auth error: %v", err)
	}
	if err = client.Mail(s.email); err != nil {
		return false, fmt.Sprintf("SSL/465 sender error: %v", err)
	}
	if err = client.Rcpt(toEmail); err != nil {
		return false, fmt.Sprintf("SSL/465 recipient error: %v", err)
	}

	w, err := client.Data()
	if err != nil {
		return false, fmt.Sprintf("SSL/465 data error: %v", err)
	}
	if _, err = w.Write(msg); err != nil {
		return false, fmt.Sprintf("SSL/465 write error: %v", err)
	}
	if err = w.Close(); err != nil {
		return false, fmt.Sprintf("SSL/465 close error: %v", err)
	}
	_ = client.Quit()

	return true, "OK (SSL/465 via " + s.server + ")"
}

func (s *Sender) tryStartTLS(msg []byte, toEmail string) (bool, string) {
	client, err := smtp.Dial(s.server + ":587")
	if err != nil {
		return false, fmt.Sprintf("STARTTLS/587 dial error: %v", err)
	}
	defer client.Close()

	if err = client.StartTLS(&tls.Config{
		ServerName: s.server,
		MinVersion: tls.VersionTLS12,
	}); err != nil {
		return false, fmt.Sprintf("STARTTLS/587 TLS error: %v", err)
	}

	if err = client.Auth(s.auth()); err != nil {
		return false, fmt.Sprintf("STARTTLS/587 auth error: %v", err)
	}
	if err = client.Mail(s.email); err != nil {
		return false, fmt.Sprintf("STARTTLS/587 sender error: %v", err)
	}
	if err = client.Rcpt(toEmail); err != nil {
		return false, fmt.Sprintf("STARTTLS/587 recipient error: %v", err)
	}

	w, err := client.Data()
	if err != nil {
		return false, fmt.Sprintf("STARTTLS/587 data error: %v", err)
	}
	if _, err = w.Write(msg); err != nil {
		return false, fmt.Sprintf("STARTTLS/587 write error: %v", err)
	}
	if err = w.Close(); err != nil {
		return false, fmt.Sprintf("STARTTLS/587 close error: %v", err)
	}
	_ = client.Quit()

	return true, "OK (STARTTLS/587 via " + s.server + ")"
}

func (s *Sender) SendEmail(toEmail, subject, htmlContent, senderName string) (bool, string) {
	msg := s.makeMessage(toEmail, subject, htmlContent, senderName)

	if _, onlyStartTLS := s.startTLSOnly[s.server]; onlyStartTLS {
		return s.tryStartTLS(msg, toEmail)
	}
	if _, onlySSL := s.sslOnly[s.server]; onlySSL {
		return s.trySSL(msg, toEmail)
	}

	ok, info := s.trySSL(msg, toEmail)
	if ok {
		return ok, info
	}

	okTLS, infoTLS := s.tryStartTLS(msg, toEmail)
	if okTLS {
		return okTLS, infoTLS
	}

	return false, info + " | " + infoTLS
}
