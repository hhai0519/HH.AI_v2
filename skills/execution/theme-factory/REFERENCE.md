> 本技能為 vendored 外部資產：來源為 Anthropic 官方範例技能 theme-factory，
> 授權 Apache-2.0（完整條款見同目錄 LICENSE.txt），本專案版本為中文化 fork。
> 修改前請先閱讀 docs/adr/0018-vendored-external-assets.md。

### 主題清單

```javascript
const THEMES = {

  // 1. 深夜科技（預設）
  "dark-tech": {
    colors: {
      bg: "#030712", surface: "#111827", border: "rgba(255,255,255,0.08)",
      text: "#f8fafc", dim: "#94a3b8",
      accent: "#0ea5e9", accent2: "#3b82f6",
      success: "#22c55e", warning: "#f59e0b", danger: "#ef4444"
    },
    gradient: "linear-gradient(135deg, #0ea5e9, #3b82f6)",
    font: { heading: "'Outfit', sans-serif", body: "'Inter', sans-serif" },
    radius: "20px", shadow: "0 25px 50px rgba(0,0,0,0.5)"
  },

  // 2. 海洋深邃
  "dark-ocean": {
    colors: {
      bg: "#0a192f", surface: "#112240", border: "rgba(100,255,218,0.1)",
      text: "#ccd6f6", dim: "#8892b0",
      accent: "#64ffda", accent2: "#57cbff",
      success: "#64ffda", warning: "#ffd700", danger: "#ff6b6b"
    },
    gradient: "linear-gradient(135deg, #64ffda, #57cbff)",
    font: { heading: "'Space Grotesk', sans-serif", body: "'Inter', sans-serif" },
    radius: "12px", shadow: "0 20px 40px rgba(0,0,0,0.6)"
  },

  // 3. 極簡白月
  "light-minimal": {
    colors: {
      bg: "#ffffff", surface: "#f8fafc", border: "#e2e8f0",
      text: "#1e293b", dim: "#64748b",
      accent: "#6366f1", accent2: "#8b5cf6",
      success: "#10b981", warning: "#f59e0b", danger: "#ef4444"
    },
    gradient: "linear-gradient(135deg, #6366f1, #8b5cf6)",
    font: { heading: "'Plus Jakarta Sans', sans-serif", body: "'Inter', sans-serif" },
    radius: "16px", shadow: "0 4px 24px rgba(0,0,0,0.08)"
  },

  // 4. 暗金奢華
  "dark-gold": {
    colors: {
      bg: "#0d0d0d", surface: "#1a1a1a", border: "rgba(201,170,113,0.2)",
      text: "#f5f0e8", dim: "#a89880",
      accent: "#c9aa71", accent2: "#e8c97a",
      success: "#7fb685", warning: "#c9aa71", danger: "#c0392b"
    },
    gradient: "linear-gradient(135deg, #c9aa71, #e8c97a)",
    font: { heading: "'Playfair Display', serif", body: "'EB Garamond', serif" },
    radius: "8px", shadow: "0 20px 60px rgba(0,0,0,0.8)"
  },

  // 5. 霓虹賽博
  "neon-cyber": {
    colors: {
      bg: "#050014", surface: "#0d001f", border: "rgba(255,0,255,0.3)",
      text: "#ffffff", dim: "#cc88ff",
      accent: "#ff00ff", accent2: "#00ffff",
      success: "#00ff88", warning: "#ffff00", danger: "#ff0040"
    },
    gradient: "linear-gradient(135deg, #ff00ff, #00ffff)",
    font: { heading: "'Orbitron', sans-serif", body: "'Share Tech Mono', monospace" },
    radius: "4px", shadow: "0 0 30px rgba(255,0,255,0.4)"
  },

  // 6. 日落漸層
  "warm-sunset": {
    colors: {
      bg: "#1a0a00", surface: "#2d1200", border: "rgba(255,160,80,0.2)",
      text: "#fff3e0", dim: "#ffb74d",
      accent: "#ff6b35", accent2: "#ffd166",
      success: "#06d6a0", warning: "#ffd166", danger: "#ef233c"
    },
    gradient: "linear-gradient(135deg, #ff6b35, #ffd166)",
    font: { heading: "'Nunito', sans-serif", body: "'Nunito', sans-serif" },
    radius: "24px", shadow: "0 20px 40px rgba(255,107,53,0.3)"
  },

  // 7. 森林自然
  "nature-green": {
    colors: {
      bg: "#0a1a0f", surface: "#0f2417", border: "rgba(78,203,113,0.2)",
      text: "#e8f5e9", dim: "#81c784",
      accent: "#4ecb71", accent2: "#a8e6cf",
      success: "#4ecb71", warning: "#ffcc02", danger: "#ff5252"
    },
    gradient: "linear-gradient(135deg, #4ecb71, #a8e6cf)",
    font: { heading: "'Poppins', sans-serif", body: "'Poppins', sans-serif" },
    radius: "20px", shadow: "0 20px 40px rgba(0,0,0,0.4)"
  },

  // 8. 冰晶極光
  "aurora": {
    colors: {
      bg: "#060b2b", surface: "#0c1445", border: "rgba(0,255,236,0.15)",
      text: "#e0f7fa", dim: "#80deea",
      accent: "#00ffec", accent2: "#7c4dff",
      success: "#00ffec", warning: "#ffea00", danger: "#ff1744"
    },
    gradient: "linear-gradient(135deg, #00ffec, #7c4dff)",
    font: { heading: "'Syne', sans-serif", body: "'Inter', sans-serif" },
    radius: "16px", shadow: "0 0 60px rgba(0,255,236,0.15)"
  },

  // 9. 企業商務
  "corporate": {
    colors: {
      bg: "#f4f5f7", surface: "#ffffff", border: "#dfe1e6",
      text: "#172b4d", dim: "#5e6c84",
      accent: "#0052cc", accent2: "#0065ff",
      success: "#00875a", warning: "#ff8b00", danger: "#de350b"
    },
    gradient: "linear-gradient(135deg, #0052cc, #0065ff)",
    font: { heading: "'Inter', sans-serif", body: "'Inter', sans-serif" },
    radius: "8px", shadow: "0 2px 8px rgba(0,0,0,0.12)"
  },

  // 10. 粉彩溫柔
  "pastel-soft": {
    colors: {
      bg: "#fef9ff", surface: "#fdf0ff", border: "#e9d5ff",
      text: "#6b21a8", dim: "#a855f7",
      accent: "#d946ef", accent2: "#f472b6",
      success: "#34d399", warning: "#fbbf24", danger: "#fb7185"
    },
    gradient: "linear-gradient(135deg, #d946ef, #f472b6)",
    font: { heading: "'Quicksand', sans-serif", body: "'Quicksand', sans-serif" },
    radius: "32px", shadow: "0 8px 30px rgba(217,70,239,0.2)"
  }
};
```

---

## 🔧 CSS 設計 Token 生成器

```javascript
function generateCSSTokens(theme) {
  const { colors, gradient, font, radius, shadow } = theme;
  return `
:root {
  /* Colors */
  --bg: ${colors.bg};
  --surface: ${colors.surface};
  --border: ${colors.border};
  --text: ${colors.text};
  --text-dim: ${colors.dim};
  --accent: ${colors.accent};
  --accent2: ${colors.accent2};
  --success: ${colors.success};
  --warning: ${colors.warning};
  --danger: ${colors.danger};
  
  /* Gradient */
  --gradient: ${gradient};
  
  /* Typography */
  --font-heading: ${font.heading};
  --font-body: ${font.body};
  
  /* Layout */
  --radius: ${radius};
  --shadow: ${shadow};
}
  `.trim();
}
```

---

