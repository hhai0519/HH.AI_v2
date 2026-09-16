/**
 * 統一 DLP 資料安全保護模組 (Unified DLP Sanitizer)
 * 同時服務 LINE Bot (CommonJS) 與 Telegram Bot (TypeScript)
 * 版本：2.1.0 (修復 Windows 反斜線路徑誤判)
 */

'use strict';

function isLikelySensitive(str) {
  // 排除條件 1：Git Commit SHA
  if (/^[0-9a-f]{40,}$/i.test(str)) return false;
  // 排除條件 2：純數字
  if (/^\d+$/.test(str)) return false;
  // 排除條件 3：看起來像 UUID
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(str)) return false;

  // 熵值評估：需包含至少 3 種字元類型
  const hasUpper = /[A-Z]/.test(str);
  const hasLower = /[a-z]/.test(str);
  const hasDigit = /[0-9]/.test(str);
  const hasSpecial = /[_-]/.test(str);
  const charTypeCount = [hasUpper, hasLower, hasDigit, hasSpecial].filter(Boolean).length;

  return charTypeCount >= 3;
}

function sanitizeDlp(text) {
  if (!text) return text;
  let sanitized = typeof text === 'object' ? JSON.stringify(text) : String(text);

  // ── Tier 1：精準模式匹配 ──
  sanitized = sanitized.replace(/AIzaSy[A-Za-z0-9_-]{33,45}/g, '[DLP_GEMINI_KEY]');
  sanitized = sanitized.replace(/\d{8,10}:[A-Za-z0-9_-]{35}/g, '[DLP_TELEGRAM_TOKEN]');
  sanitized = sanitized.replace(/(eyJhbGciOiJIUzI1NiJ9\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)/g, '[DLP_LINE_JWT]');
  sanitized = sanitized.replace(/postgres:\/\/([^:]+):([^@]+)@/g, 'postgres://$1:[DLP_DB_PWD]@');

  // ── Tier 2：啟發式 Token 檢測（40字元以上且具備高隨機性） ──
  sanitized = sanitized.replace(/\b([A-Za-z0-9_-]{40,})\b/g, (match) => {
    // 排除 Windows/Unix 路徑
    if (match.includes('/') || match.includes('\\') || match.includes(':')) return match;
    return isLikelySensitive(match) ? '[DLP_LONG_TOKEN]' : match;
  });

  return sanitized;
}

module.exports = { sanitizeDlp };
