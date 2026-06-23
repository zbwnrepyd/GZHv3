/* layout-app.js — Markdown-first 排版中心
   加载 render-data → 每卡 Markdown → 实时预览 → 保存 layout → 导出 */
const LayoutApp = {
  _assetTokenExamples: '{{logo}} {{founder_photo}} {{chart_competitive}}',
  _company: '',
  _setKey: 'v1',
  _data: null,
  _cards: [],
  _templates: [],
  _activeCardId: null,
  _activeCard: null,
  _markdownByCard: {},
  _styleByCard: {},
  _layoutOverrides: {},
  _assetByKey: {},
  _mode: 'split',
  _splitRatio: 0.58,
  _previewScale: 1,
  _styleAppliedToAllDirty: false,
  _defaultStyle: {
    fontSize: 32,
    lineHeight: 1.6,
    paragraphGap: 22,
    padding: 74,
    bgColor: '#FFFFFF',
    textColor: '#172033',
    accentColor: '#29B8D4',
    imageMaxHeight: 360,
  },

  async init() {
    const p = new URLSearchParams(window.location.search);
    this._company = p.get('company') || '';
    this._setKey = p.get('set') || 'v1';
    if (!this._company) {
      document.getElementById('canvas-area').innerHTML = '<div class="empty-state">缺少 ?company= 参数</div>';
      return;
    }

    document.getElementById('company-label').textContent = `排版 · ${this._company}`;
    document.getElementById('btn-back-editor').href = `/editor?company=${encodeURIComponent(this._company)}&set=${this._setKey}`;
    this._bindChrome();
    this._setStatus('加载中');
    await this._loadData();
    await this._loadTemplates();
    this._renderCardList();
    this._renderTemplateSelect();
    this._setMode('split');
    this._restoreLocal();
    this._renderAssetTokenHelp();
    if (this._cards.length) this._selectCard(this._cards[0].card_id);
  },

  _bindChrome() {
    document.getElementById('btn-template-maker').addEventListener('click', () => {
      window.open('/template-maker', '_blank');
    });
    document.getElementById('btn-export').addEventListener('click', () => this._exportPNG());
    document.getElementById('btn-apply-template').addEventListener('click', () => this._applyTemplate());
    document.getElementById('btn-save-layout').addEventListener('click', () => this._saveLayout());
    document.getElementById('btn-save-local').addEventListener('click', () => this._saveLocalCurrent());
    document.getElementById('btn-save-local-all').addEventListener('click', () => this._saveLocalAll());
    document.getElementById('btn-reset-layout').addEventListener('click', () => this._resetLayout());
    document.getElementById('btn-apply-style-all').addEventListener('click', () => this._applyStyleToAllCards());
    document.getElementById('btn-fit-preview').addEventListener('click', () => this._fitPreview());
    // 高级样式弹窗
    document.getElementById('btn-advanced-style').addEventListener('click', () => this._toggleAdvancedStyle());
    document.getElementById('btn-asp-apply').addEventListener('click', () => this._applyAdvancedStyle());
    document.getElementById('btn-asp-cancel').addEventListener('click', () => this._hideAdvancedStyle());
    document.querySelectorAll('.asp-align').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.asp-align').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
      });
    });
    document.getElementById('markdown-editor').addEventListener('input', () => {
      if (!this._activeCardId) return;
      this._markdownByCard[this._activeCardId] = document.getElementById('markdown-editor').value;
      this._debouncedPreview();
      this._autoSave();
    });
    document.getElementById('markdown-toolbar').addEventListener('click', event => {
      const btn = event.target.closest('[data-action]');
      if (!btn) return;
      this._handleToolbarAction(btn.dataset.action, btn.dataset.value || '');
    });
    ['font-size', 'line-height', 'paragraph-gap', 'padding', 'image-max-height', 'bg-color', 'text-color', 'accent-color'].forEach(key => {
      document.getElementById(`style-${key}`).addEventListener('input', () => this._onStyleInput());
    });
    document.getElementById('splitter').addEventListener('mousedown', event => this._startSplitDrag(event));
    window.addEventListener('resize', () => this._fitPreview());
  },

  async _loadData() {
    try {
      const r = await fetch(`/api/render-data/${encodeURIComponent(this._company)}?set=${this._setKey}`);
      if (!r.ok) throw new Error(`render-data ${r.status}`);
      this._data = await r.json();
      this._cards = (this._data.cards || []).map((card, index) => this._normalizeRenderCard(card, index));
      this._assetByKey = {};
      this._cards.forEach(card => {
        (card.items || []).forEach(item => {
          if (item.item_type === 'media') {
            this._assetByKey[item.item_key] = item;
          }
        });
        const layout = card.layout || {};
        this._markdownByCard[card.card_id] = layout.markdown || this._defaultMarkdownForCard(card) || this._markdownFromCard(card);
        this._styleByCard[card.card_id] = {
          ...this._defaultStyle,
          ...(layout.style || this._styleFromTemplate(card.template)),
        };
      });
      this._setStatus(`已加载 ${this._cards.length} 张卡`);
    } catch (e) {
      console.error('加载 render-data 失败:', e);
      this._cards = [];
      this._setStatus('加载失败');
    }
  },

  _normalizeRenderCard(card, index) {
    const rawLayout = card.layout || {};
    const templateId = card.template_id || rawLayout.template_id || '';
    const items = [
      ...(card.items || []).map(item => this._normalizeRenderItem(item, 'field')),
      ...(card.media || []).map(item => this._normalizeRenderItem(item, 'media')),
    ].filter(Boolean);

    return {
      ...card,
      card_index: card.card_index ?? index + 1,
      card_title: card.card_title || card.title || `卡片${index + 1}`,
      enabled: card.enabled !== false,
      template_id: templateId,
      items,
      layout: {
        ...rawLayout,
        overrides: rawLayout.overrides || {},
      },
    };
  },

  _normalizeRenderItem(item, defaultType = 'field') {
    if (!item) return null;
    const type = item.item_type || (item.asset_key ? 'media' : defaultType);
    if (type === 'media') {
      const key = item.item_key || item.asset_key;
      if (!key) return null;
      return {
        ...item,
        item_type: 'media',
        item_key: key,
        item_label: item.item_label || item.media_label || item.label || key,
        media_label: item.media_label || item.item_label || item.label || key,
        url: item.url || '',
      };
    }

    const key = item.item_key || item.field_key;
    if (!key) return null;
    return {
      ...item,
      item_type: 'field',
      item_key: key,
      item_label: item.item_label || item.field_label || item.label || key,
      field_label: item.field_label || item.item_label || item.label || key,
      value: item.value ?? '',
      display_role: item.display_role || item.role || 'body',
    };
  },

  async _loadTemplates() {
    this._templates = [];
    try {
      const r = await fetch('/api/templates');
      if (r.ok) {
        const d = await r.json();
        this._templates = d.templates || [];
      }
    } catch { /* keep empty */ }
    try {
      const r2 = await fetch('/api/svg-templates');
      if (r2.ok) {
        const d2 = await r2.json();
        this._templates = [...this._templates, ...(d2.templates || [])];
      }
    } catch { /* keep existing */ }
  },

  _renderCardList() {
    const el = document.getElementById('card-list');
    el.innerHTML = this._cards.map(c => `
      <div class="layout-card-item" data-card-id="${this._escAttr(c.card_id)}" id="card-item-${this._escAttr(c.card_id)}">
        <span class="layout-card-idx">${this._esc(c.card_index)}</span>
        <span class="layout-card-title">${this._esc(c.card_title)}</span>
        <span class="layout-card-badge">${(c.items || []).length}项</span>
      </div>
    `).join('');
    el.querySelectorAll('.layout-card-item').forEach(item => {
      item.addEventListener('click', () => this._selectCard(item.dataset.cardId));
    });
  },

  _renderTemplateSelect() {
    const sel = document.getElementById('template-select');
    sel.innerHTML = '<option value="">默认 Markdown 卡片</option>' +
      this._templates.map(t => {
        const id = t.id || t.template_id || '';
        const name = t.name || t.template_name || id || '未命名模板';
        return `<option value="${this._escAttr(id)}">${this._esc(name)}</option>`;
      }).join('');
  },

  _selectCard(cardId) {
    this._activeCardId = cardId;
    this._activeCard = this._cards.find(c => c.card_id === cardId);
    if (!this._activeCard) return;
    this._layoutOverrides = this._activeCard.layout?.overrides || {};
    document.querySelectorAll('.layout-card-item').forEach(el => {
      el.classList.toggle('active', el.dataset.cardId === cardId);
    });
    document.getElementById('active-card-title').textContent =
      `${this._activeCard.card_index}. ${this._activeCard.card_title}`;
    document.getElementById('template-select').value = this._activeCard.template_id || '';
    document.getElementById('markdown-editor').value = this._markdownByCard[cardId] || '';
    this._syncStylePanel();
    this._renderMarkdownPreview();
  },

  _markdownFromCard(card) {
    const lines = [];
    const items = card.items || [];
    const fields = items.filter(item => item.item_type === 'field' && String(item.value || '').trim());
    const media = items.filter(item => item.item_type === 'media');
    const titleFields = fields.filter(item => (item.display_role || '') === 'title');
    const subtitleFields = fields.filter(item => (item.display_role || '') === 'subtitle');
    const bodyFields = fields.filter(item => !['title', 'subtitle'].includes(item.display_role || 'body'));

    if (titleFields.length) {
      titleFields.forEach(item => lines.push(`# ${item.value}`));
    } else if (card.card_title) {
      lines.push(`# ${card.card_title}`);
    }
    subtitleFields.forEach(item => lines.push(`\n## ${item.value}`));
    media.forEach(item => {
      if (item.url) lines.push(`\n{{${item.item_key}}}`);
    });
    bodyFields.forEach(item => {
      const label = item.item_label || item.field_label || '';
      const value = String(item.value || '').trim();
      if (!value) return;
      if (label && value !== label) {
        lines.push(`\n### ${label}\n${value}`);
      } else {
        lines.push(`\n${value}`);
      }
    });
    return lines.join('\n').replace(/\n{4,}/g, '\n\n\n').trim();
  },

  _defaultMarkdownForCard(card) {
    if (!card) return '';
    const fields = {};
    const media = [];
    (card.items || []).forEach(item => {
      if (item.item_type === 'field') fields[item.item_key] = String(item.value || '').trim();
      if (item.item_type === 'media') media.push(item);
    });
    const mediaToken = key => media.some(item => item.item_key === key) ? `{{${key}}}` : '';
    const present = keys => keys.map(key => fields[key]).filter(Boolean);
    const heading = title => `<span style="display:block;text-align:left;font-size:50px"># ${title}</span>`;

    if (card.card_id === 'v2_card_01' || Number(card.card_index) === 1) {
      const name = fields.company_name || this._company || card.card_title || '';
      const type = fields.company_type || '';
      return [
        '<br>',
        '<span style="display:block;text-align:center;font-size:50px">## 3分钟拆解一家盈利AI初创公司</span>',
        '<br>',
        '<br>',
        '',
        '<br>',
        mediaToken('logo'),
        '<br>',
        '<br>',
        '',
        `<span style="display:block;text-align:center"># ${this._esc(name)}</span>`,
        '',
        type ? `<span style="display:block;text-align:center;font-size:34px">${this._esc(type)}</span>` : '',
      ].filter(line => line !== '').join('\n');
    }

    const image = media[0] ? `{{${media[0].item_key}}}` : '';
    const body = present((card.items || [])
      .filter(item => item.item_type === 'field')
      .map(item => item.item_key));
    if (!body.length && !image) return '';
    return [heading(card.card_title || '内容页'), '', image, '', ...body]
      .filter(line => line !== '')
      .join('\n\n')
      .replace(/\n{5,}/g, '\n\n\n');
  },

  _styleFromTemplate(template) {
    const style = {};
    const regions = template?.regions || [];
    const bodyRegion = regions.find(r => r.type === 'text' && (r.role || 'body') === 'body') ||
      regions.find(r => r.type === 'text');
    if (bodyRegion?.style?.fontSize) style.fontSize = bodyRegion.style.fontSize;
    if (bodyRegion?.style?.lineHeight) style.lineHeight = bodyRegion.style.lineHeight;
    if (template?.background?.type === 'color' && template.background.value) {
      style.bgColor = template.background.value;
      style.textColor = this._readableTextColor(template.background.value);
    }
    if (bodyRegion?.style?.color) style.textColor = bodyRegion.style.color;
    return style;
  },

  _syncStylePanel() {
    const style = this._currentStyle();
    document.getElementById('style-font-size').value = style.fontSize;
    document.getElementById('style-line-height').value = style.lineHeight;
    document.getElementById('style-paragraph-gap').value = style.paragraphGap;
    document.getElementById('style-padding').value = style.padding;
    document.getElementById('style-bg-color').value = style.bgColor;
    document.getElementById('style-text-color').value = style.textColor;
    document.getElementById('style-accent-color').value = style.accentColor;
    document.getElementById('style-image-max-height').value = style.imageMaxHeight;
  },

  _onStyleInput() {
    if (!this._activeCardId) return;
    this._styleByCard[this._activeCardId] = {
      fontSize: Number(document.getElementById('style-font-size').value || this._defaultStyle.fontSize),
      lineHeight: Number(document.getElementById('style-line-height').value || this._defaultStyle.lineHeight),
      paragraphGap: Number(document.getElementById('style-paragraph-gap').value || this._defaultStyle.paragraphGap),
      padding: Number(document.getElementById('style-padding').value || this._defaultStyle.padding),
      bgColor: document.getElementById('style-bg-color').value || this._defaultStyle.bgColor,
      textColor: document.getElementById('style-text-color').value || this._defaultStyle.textColor,
      accentColor: document.getElementById('style-accent-color').value || this._defaultStyle.accentColor,
      imageMaxHeight: Number(document.getElementById('style-image-max-height').value || this._defaultStyle.imageMaxHeight),
    };
    this._debouncedPreview();
    this._autoSave();
  },

  _currentStyle() {
    return { ...this._defaultStyle, ...(this._styleByCard[this._activeCardId] || {}) };
  },

  _debouncedPreview() {
    clearTimeout(this._previewTimer);
    this._previewTimer = setTimeout(() => this._renderMarkdownPreview(), 80);
  },

  // 自动保存：每次编辑 → localStorage 即时 + 服务端 2s 防抖（静默，无提示）
  _autoSave() {
    if (!this._activeCardId) return;
    // 即刻写入 localStorage
    this._saveLocalCurrentSilent();
    // 防抖写入服务端
    clearTimeout(this._autoSaveTimer);
    this._autoSaveTimer = setTimeout(() => {
      this._saveLayoutSilent().catch(() => {});
    }, 2000);
  },

  _saveLocalCurrentSilent() {
    if (!this._activeCardId) return;
    const data = this._loadLocalData();
    data.markdownByCard[this._activeCardId] = this._markdownByCard[this._activeCardId] || '';
    data.styleByCard[this._activeCardId] = { ...this._currentStyle() };
    this._writeLocalData(data);
  },

  async _saveLayoutSilent() {
    if (!this._activeCardId) return;
    try {
      await fetch(`/api/layout/${encodeURIComponent(this._company)}/${encodeURIComponent(this._activeCardId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layout: this._layoutPayload() }),
      });
    } catch (_) { /* 静默失败，下次操作会重试 */ }
  },

  _renderMarkdownPreview() {
    const iframe = document.getElementById('preview-frame');
    const status = document.getElementById('preview-status');
    if (!this._activeCardId || !iframe) return;
    const markdown = this._markdownByCard[this._activeCardId] || '';
    const style = this._currentStyle();
    iframe.srcdoc = this._buildPreviewHtml(markdown, style);
    if (status) status.textContent = '已同步';
    requestAnimationFrame(() => this._fitPreview());
  },

  _buildPreviewHtml(markdown, style) {
    const body = this._renderMarkdownToHtml(markdown);
    return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; width: 900px; height: 1200px; overflow: hidden; }
  body {
    background: ${style.bgColor};
    color: ${style.textColor};
    font-family: "Noto Sans SC", "Instrument Sans", sans-serif;
    font-size: ${style.fontSize}px;
    line-height: ${style.lineHeight};
    letter-spacing: 0;
  }
  .layout-md-card {
    position: relative;
    width: 900px;
    height: 1200px;
    padding: ${style.padding}px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }
  .layout-md-body {
    flex: 1;
    display: flex;
    flex-direction: column;
  }
  .layout-md-spacer { flex: 1; }
  .layout-md-body > * { margin: 0 0 ${style.paragraphGap}px; }
  .layout-md-body > *:last-child { margin-bottom: 0; }
  h1, h2, h3 { margin-top: 0; }
  h1 {
    font-size: ${Math.round(style.fontSize * 1.9)}px;
    line-height: 1.08;
    font-weight: 900;
    color: ${style.textColor};
    margin-bottom: ${Math.round(style.paragraphGap * 1.4)}px;
  }
  h2 {
    font-size: ${Math.round(style.fontSize * 1.28)}px;
    line-height: 1.16;
    color: ${style.accentColor};
    font-weight: 800;
  }
  h3 {
    font-size: ${Math.round(style.fontSize * 1.05)}px;
    line-height: 1.2;
    color: ${style.textColor};
    font-weight: 700;
  }
  p, li, blockquote { word-wrap: break-word; }
  ul { padding-left: 1.2em; }
  blockquote {
    border-left: 6px solid ${style.accentColor};
    padding: 10px 14px;
    background: rgba(41, 184, 212, .09);
    border-radius: 0 8px 8px 0;
  }
  strong { font-weight: 900; }
  em { font-style: italic; }
  a { color: ${style.accentColor}; text-decoration: none; }
  img.layout-md-image, .layout-asset img {
    display: block;
    max-width: 100%;
    max-height: ${style.imageMaxHeight}px;
    object-fit: contain;
    border-radius: 10px;
  }
  .layout-asset {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 120px;
    border-radius: 12px;
    overflow: hidden;
  }
  .layout-asset-missing {
    padding: 18px;
    color: rgba(15, 23, 42, .38);
    border: 1px dashed rgba(15, 23, 42, .18);
  }
</style></head><body>
  <article class="layout-md-card" data-od-id="card-root">
    <div class="layout-md-body">${body}</div>
  </article>
</body></html>`;
  },

  _renderMarkdownToHtml(markdown) {
    const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n');
    const html = [];
    let listOpen = false;
    const closeList = () => {
      if (listOpen) {
        html.push('</ul>');
        listOpen = false;
      }
    };

    const _unwrapInline = (line) => {
      const m = line.match(/^(<(span|mark|center)\b[^>]*>)(.*?)(<\/\2>)$/i);
      return m ? { open: m[1], close: m[4], inner: m[3].trim() } : null;
    };

    // 从 wrapper span 中提取 font-size，转移到 heading 上，避免被 CSS 覆盖
    const _extractFontSize = (open) => {
      const m = (open || '').match(/font-size:\s*(\d+)px/i);
      return m ? ` style="font-size:${m[1]}px"` : '';
    };

    const _headingTag = (level, wrap, inner) => {
      const tag = `h${level}`;
      const extra = wrap ? _extractFontSize(wrap.open) : '';
      const content = this._inlineMarkdown(inner);
      return wrap
        ? `${wrap.open.replace(/font-size:\s*\d+px;?/gi, '')}<${tag}${extra}>${content}</${tag}>${wrap.close}`
        : `<${tag}>${content}</${tag}>`;
    };

    lines.forEach(rawLine => {
      const line = rawLine.trim();
      if (!line) {
        closeList();
        return;
      }
      const wrap = _unwrapInline(line);
      const body = wrap ? wrap.inner : line;
      const assetOnly = body.match(/^\{\{([a-zA-Z0-9_:-]+)\}\}$/);
      const imageOnly = body.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
      if (assetOnly) {
        closeList();
        html.push(this._assetHtml(assetOnly[1]));
      } else if (imageOnly) {
        closeList();
        html.push(`<p><img class="layout-md-image" src="${this._escAttr(imageOnly[2])}" alt="${this._escAttr(imageOnly[1])}"></p>`);
      } else if (body.startsWith('# ')) {
        closeList();
        html.push(_headingTag(1, wrap, body.slice(2)));
      } else if (body.startsWith('## ')) {
        closeList();
        html.push(_headingTag(2, wrap, body.slice(3)));
      } else if (body.startsWith('### ')) {
        closeList();
        html.push(_headingTag(3, wrap, body.slice(4)));
      } else if (body === '---') {
        closeList();
        html.push('<div class="layout-md-spacer"></div>');
      } else if (body.startsWith('> ')) {
        closeList();
        html.push(wrap ? `${wrap.open}<blockquote>${this._inlineMarkdown(body.slice(2))}</blockquote>${wrap.close}` : `<blockquote>${this._inlineMarkdown(body.slice(2))}</blockquote>`);
      } else if (/^[-*]\s+/.test(body)) {
        if (!listOpen) {
          html.push('<ul>');
          listOpen = true;
        }
        html.push(wrap ? `${wrap.open}<li>${this._inlineMarkdown(body.replace(/^[-*]\s+/, ''))}</li>${wrap.close}` : `<li>${this._inlineMarkdown(body.replace(/^[-*]\s+/, ''))}</li>`);
      } else {
        closeList();
        html.push(`<p>${this._inlineMarkdown(line)}</p>`);
      }
    });
    closeList();
    return html.join('\n');
  },

  _inlineMarkdown(text) {
    const preserved = [];
    let safe = String(text || '')
      .replace(/<br\s*\/?>/gi, match => {
        const token = `@@HTML_${preserved.length}@@`;
        preserved.push(match);
        return token;
      })
      .replace(/<(span|mark)\b[^>]*>.*?<\/\1>/g, match => {
        const token = `@@HTML_${preserved.length}@@`;
        preserved.push(match);
        return token;
      });
    safe = this._esc(safe)
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\*([^*]+)\*/g, '<em>$1</em>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, label, url) =>
        `<a href="${this._escAttr(url)}">${label}</a>`)
      .replace(/\{\{([a-zA-Z0-9_:-]+)\}\}/g, (_m, key) => this._assetHtml(key));
    preserved.forEach((html, index) => {
      safe = safe.replace(`@@HTML_${index}@@`, this._sanitizeInlineHtml(html));
    });
    return safe;
  },

  _sanitizeInlineHtml(html) {
    return String(html || '')
      .replace(/<(?!\/?(span|mark|br)\b)/g, '&lt;')
      .replace(/\son[a-z]+\s*=/gi, ' data-blocked=')
      .replace(/javascript:/gi, '');
  },

  _assetHtml(key) {
    const asset = this._resolveAssetToken(key);
    if (!asset?.url) {
      return `<div class="layout-asset layout-asset-missing">{{${this._esc(key)}}} 未选择素材</div>`;
    }
    return `<figure class="layout-asset" data-asset-key="${this._escAttr(key)}">
      <img src="${this._escAttr(asset.url)}" alt="${this._escAttr(asset.media_label || key)}">
    </figure>`;
  },

  _resolveAssetToken(key) {
    return this._assetByKey[key] || null;
  },

  _readableTextColor(hex) {
    const m = String(hex || '').trim().match(/^#?([0-9a-f]{6})$/i);
    if (!m) return this._defaultStyle.textColor;
    const raw = m[1];
    const r = parseInt(raw.slice(0, 2), 16);
    const g = parseInt(raw.slice(2, 4), 16);
    const b = parseInt(raw.slice(4, 6), 16);
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return luminance < 0.52 ? '#F8FAFC' : '#172033';
  },

  _toggleAdvancedStyle() {
    const popover = document.getElementById('advanced-style-popover');
    popover.style.display = popover.style.display === 'none' ? 'flex' : 'none';
  },

  _hideAdvancedStyle() {
    document.getElementById('advanced-style-popover').style.display = 'none';
  },

  _applyAdvancedStyle() {
    const alignBtn = document.querySelector('.asp-align.active');
    const align = alignBtn ? alignBtn.dataset.align : 'left';
    const fontFamily = document.getElementById('asp-font-family').value;
    const fontSize = document.getElementById('asp-font-size').value || 24;
    const editor = document.getElementById('markdown-editor');
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const selected = editor.value.slice(start, end) || '文字';
    const styles = [`display:block`, `text-align:${align}`, `font-size:${fontSize}px`];
    if (fontFamily) styles.unshift(`font-family:'${fontFamily}',sans-serif`);
    const open = `<span style="${styles.join(';')}">`;
    const close = '</span>';
    editor.setRangeText(`${open}${selected}${close}`, start, end, 'select');
    this._markdownByCard[this._activeCardId] = editor.value;
    this._hideAdvancedStyle();
    this._renderMarkdownPreview();
  },

  _handleToolbarAction(action, value) {
    const editor = document.getElementById('markdown-editor');
    editor.focus();
    if (action === 'bold') this._wrapSelection('**', '**', '加粗文字');
    if (action === 'italic') this._wrapSelection('*', '*', '斜体文字');
    if (action === 'h1') this._prefixSelection('# ');
    if (action === 'h2') this._prefixSelection('## ');
    if (action === 'quote') this._prefixSelection('> ');
    if (action === 'list') this._prefixSelection('- ');
    if (action === 'image') this._insertMarkdown('![图片描述](图片URL)');
    if (action === 'link') this._wrapSelection('[', '](https://)', '链接文字');
    if (action === 'color') this._wrapSelection(`<span style="color:${value}">`, '</span>', '文字');
    if (action === 'bg') this._wrapSelection(`<mark style="background:${value};border-radius:3px;padding:0 2px">`, '</mark>', '高亮文字');
    if (action === 'br') this._insertMarkdown('<br>');
    if (action === 'spacer') this._insertMarkdown('\n---\n');
    if (action === 'center') this._wrapSelection('<span style="display:block;text-align:center">', '</span>', '居中文字');
    if (action === 'clear') this._clearInlineStyle();
  },

  _wrapSelection(open, close, placeholder = '') {
    const editor = document.getElementById('markdown-editor');
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const selected = editor.value.slice(start, end) || placeholder;
    const next = `${open}${selected}${close}`;
    editor.setRangeText(next, start, end, 'select');
    editor.selectionStart = start + open.length;
    editor.selectionEnd = start + open.length + selected.length;
    this._markdownByCard[this._activeCardId] = editor.value;
    this._renderMarkdownPreview();
  },

  _prefixSelection(prefix) {
    const editor = document.getElementById('markdown-editor');
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const selected = editor.value.slice(start, end) || '文本';
    const next = selected.split('\n').map(line => `${prefix}${line}`).join('\n');
    editor.setRangeText(next, start, end, 'select');
    this._markdownByCard[this._activeCardId] = editor.value;
    this._renderMarkdownPreview();
  },

  _insertMarkdown(text) {
    const editor = document.getElementById('markdown-editor');
    const start = editor.selectionStart;
    const pad = start > 0 && editor.value[start - 1] !== '\n' ? '\n' : '';
    editor.setRangeText(`${pad}${text}`, start, editor.selectionEnd, 'end');
    this._markdownByCard[this._activeCardId] = editor.value;
    this._renderMarkdownPreview();
  },

  _clearInlineStyle() {
    const editor = document.getElementById('markdown-editor');
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const scope = start === end ? editor.value : editor.value.slice(start, end);
    const cleaned = scope.replace(/<\/?(span|mark)[^>]*>/g, '');
    if (start === end) editor.value = cleaned;
    else editor.setRangeText(cleaned, start, end, 'select');
    this._markdownByCard[this._activeCardId] = editor.value;
    this._renderMarkdownPreview();
  },

  _applyStyleToAllCards() {
    if (!this._activeCardId) return;
    const style = { ...this._currentStyle() };
    this._cards.forEach(card => {
      this._styleByCard[card.card_id] = { ...style };
    });
    this._styleAppliedToAllDirty = true;
    this._setStatus('样式已应用到全套，记得保存');
    this._renderMarkdownPreview();
  },

  _renderAssetTokenHelp() {
    const el = document.getElementById('asset-token-list');
    if (!el) return;
    const entries = Object.entries(this._assetByKey);
    if (!entries.length) {
      el.innerHTML = '<span>暂无图片素材，请先在图片定稿台采集</span>';
      return;
    }
    el.innerHTML = entries.map(([key, item]) => {
      const label = item.media_label || item.item_label || key;
      return '<code>' + this._esc(label) + '：{{' + this._esc(key) + '}}</code>';
    }).join('');
    const hint = document.createElement('span');
    hint.textContent = ' 或 ![](...)';
    el.appendChild(hint);
  },

  _lsKey() {
    return `layout_local:${this._company}:${this._setKey}`;
  },

  _saveLocalCurrent() {
    if (!this._activeCardId) return;
    const data = this._loadLocalData();
    data.markdownByCard[this._activeCardId] = this._markdownByCard[this._activeCardId] || '';
    data.styleByCard[this._activeCardId] = { ...this._currentStyle() };
    this._writeLocalData(data);
    this._setStatus('当前卡片已暂存到浏览器');
  },

  _saveLocalAll() {
    const data = this._loadLocalData();
    this._cards.forEach(card => {
      data.markdownByCard[card.card_id] = this._markdownByCard[card.card_id] || '';
      data.styleByCard[card.card_id] = { ...this._defaultStyle, ...(this._styleByCard[card.card_id] || {}) };
    });
    this._writeLocalData(data);
    this._setStatus(`全部 ${this._cards.length} 张卡片已暂存到浏览器`);
  },

  _loadLocalData() {
    try {
      const raw = localStorage.getItem(this._lsKey());
      if (raw) {
        const parsed = JSON.parse(raw);
        return {
          markdownByCard: parsed.markdownByCard || {},
          styleByCard: parsed.styleByCard || {},
        };
      }
    } catch {}
    return { markdownByCard: {}, styleByCard: {} };
  },

  _writeLocalData(data) {
    try {
      localStorage.setItem(this._lsKey(), JSON.stringify({
        markdownByCard: data.markdownByCard,
        styleByCard: data.styleByCard,
        savedAt: new Date().toISOString(),
      }));
    } catch (e) {
      alert('暂存失败: ' + e.message);
    }
  },

  _restoreLocal() {
    const data = this._loadLocalData();
    const mdKeys = Object.keys(data.markdownByCard);
    const stKeys = Object.keys(data.styleByCard);
    if (!mdKeys.length && !stKeys.length) return;
    mdKeys.forEach(cardId => {
      if (this._markdownByCard.hasOwnProperty(cardId)) {
        this._markdownByCard[cardId] = data.markdownByCard[cardId];
      }
    });
    stKeys.forEach(cardId => {
      if (this._styleByCard.hasOwnProperty(cardId)) {
        this._styleByCard[cardId] = { ...this._defaultStyle, ...data.styleByCard[cardId] };
      }
    });
    const count = new Set([...mdKeys, ...stKeys]).size;
    this._setStatus(`已从浏览器恢复 ${count} 张卡片的暂存`);
  },

  _setMode(mode) {
    this._mode = 'split';
    requestAnimationFrame(() => this._fitPreview());
  },

  _startSplitDrag(event) {
    if (this._mode !== 'split') return;
    event.preventDefault();
    const shell = document.getElementById('editor-shell');
    const move = moveEvent => {
      const rect = shell.getBoundingClientRect();
      const ratio = (moveEvent.clientX - rect.left) / rect.width;
      this._splitRatio = Math.min(0.72, Math.max(0.32, ratio));
      shell.style.gridTemplateColumns =
        `minmax(320px, ${this._splitRatio}fr) 8px minmax(300px, ${1 - this._splitRatio}fr)`;
      this._fitPreview();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  },

  _fitPreview() {
    const frame = document.getElementById('preview-frame');
    const wrap = document.getElementById('preview-frame-wrap');
    const stage = document.getElementById('preview-stage');
    if (!frame || !wrap || !stage || this._mode === 'write') return;
    const scale = Math.min((stage.clientWidth - 48) / 900, (stage.clientHeight - 48) / 1200, 1);
    this._previewScale = Math.max(0.2, scale);
    wrap.style.width = `${900 * this._previewScale}px`;
    wrap.style.height = `${1200 * this._previewScale}px`;
    frame.style.transform = `scale(${this._previewScale})`;
    frame.style.width = '900px';
    frame.style.height = '1200px';
  },

  _effectiveTemplate() {
    return this._activeCard?.template || {};
  },

  async _applyTemplate() {
    const tid = document.getElementById('template-select').value;
    if (!this._activeCardId) return;
    const currentMarkdown = this._markdownByCard[this._activeCardId] || '';
    try {
      const r = await fetch(`/api/card-config/${encodeURIComponent(this._company)}/cards/${encodeURIComponent(this._activeCardId)}?set=${this._setKey}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_id: tid }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await this._loadData();
      this._markdownByCard[this._activeCardId] = currentMarkdown;
      this._selectCard(this._activeCardId);
      this._autoSave();
      this._setStatus('模板已应用，正文已保留');
    } catch (e) {
      alert('应用失败: ' + e.message);
    }
  },

  _layoutPayload(cardId = this._activeCardId) {
    const card = this._cards.find(c => c.card_id === cardId) || this._activeCard || {};
    return {
      mode: 'markdown_first',
      markdown: this._markdownByCard[cardId] || '',
      style: { ...this._defaultStyle, ...(this._styleByCard[cardId] || {}) },
      template_id: card.template_id || '',
      overrides: card.layout?.overrides || {},
    };
  },

  async _saveLayout() {
    if (!this._activeCardId) return;
    if (this._styleAppliedToAllDirty) {
      await this._saveAllLayouts();
      return;
    }
    try {
      const r = await fetch(`/api/layout/${encodeURIComponent(this._company)}/${encodeURIComponent(this._activeCardId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layout: this._layoutPayload() }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      this._setStatus('排版已保存');
    } catch (e) {
      alert('保存失败: ' + e.message);
    }
  },

  async _saveAllLayouts() {
    try {
      for (const card of this._cards) {
        const r = await fetch(`/api/layout/${encodeURIComponent(this._company)}/${encodeURIComponent(card.card_id)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ layout: this._layoutPayload(card.card_id) }),
        });
        if (!r.ok) throw new Error(`${card.card_id} HTTP ${r.status}`);
      }
      this._styleAppliedToAllDirty = false;
      this._setStatus('全套样式已保存');
    } catch (e) {
      alert('保存失败: ' + e.message);
    }
  },

  async _resetLayout() {
    if (!this._activeCardId) return;
    if (!confirm('重置当前卡片排版？Markdown 会恢复为定稿台内容。')) return;
    try {
      await fetch(`/api/layout/${encodeURIComponent(this._company)}/${encodeURIComponent(this._activeCardId)}/reset`, { method: 'POST' });
      await this._loadData();
      this._selectCard(this._activeCardId);
      this._setStatus('已重置');
    } catch (e) {
      alert('重置失败: ' + e.message);
    }
  },

  _exportPNG() {
    this._showExportDialog();
  },

  _showExportDialog() {
    if (document.getElementById('export-dialog-overlay')) return;
    const overlay = document.createElement('div');
    overlay.id = 'export-dialog-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:999;display:flex;align-items:center;justify-content:center';
    overlay.innerHTML = `
      <div style="background:var(--surface-1, #fff);border-radius:12px;padding:24px;min-width:360px;max-width:420px;box-shadow:0 8px 40px rgba(0,0,0,.2)">
        <h3 style="margin:0 0 16px;font-size:16px;color:var(--text, #1B2A4A)">导出卡片</h3>
        <div style="display:flex;flex-direction:column;gap:14px">
          <label style="font-size:13px;color:var(--text-muted, #556B82)">
            导出范围
            <select id="export-range" style="width:100%;margin-top:4px;padding:6px 8px;border:1px solid var(--border, #E2E4E9);border-radius:6px;font-size:13px">
              <option value="current">当前卡片</option>
              <option value="all">全部启用卡片</option>
            </select>
          </label>
          <label style="font-size:13px;color:var(--text-muted, #556B82)">
            格式
            <select id="export-format" style="width:100%;margin-top:4px;padding:6px 8px;border:1px solid var(--border, #E2E4E9);border-radius:6px;font-size:13px">
              <option value="png">PNG（单个文件）</option>
              <option value="zip">ZIP（打包下载）</option>
            </select>
          </label>
          <label style="font-size:13px;color:var(--text-muted, #556B82)">
            倍率
            <select id="export-scale" style="width:100%;margin-top:4px;padding:6px 8px;border:1px solid var(--border, #E2E4E9);border-radius:6px;font-size:13px">
              <option value="1">1x</option>
              <option value="2" selected>2x</option>
              <option value="3">3x</option>
            </select>
          </label>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:20px">
          <button id="export-dialog-cancel" style="padding:7px 16px;border:1px solid var(--border, #E2E4E9);border-radius:6px;background:var(--surface-1, #fff);font-size:13px;cursor:pointer">取消</button>
          <button id="export-dialog-confirm" style="padding:7px 20px;border:none;border-radius:6px;background:var(--cyan, #29B8D4);color:#fff;font-size:13px;font-weight:600;cursor:pointer">开始导出</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#export-dialog-cancel').onclick = () => overlay.remove();
    overlay.querySelector('#export-dialog-confirm').onclick = () => {
      const range = document.getElementById('export-range').value;
      const format = document.getElementById('export-format').value;
      const scale = parseInt(document.getElementById('export-scale').value, 10);
      overlay.remove();
      this._startExport({ range, format, scale });
    };
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  },

  async _startExport(opts = {}) {
    try {
      this._setStatus('导出中');
      await this._saveLayout();
      const payload = {
        card_ids: opts.range === 'current' && this._activeCardId ? [this._activeCardId] : undefined,
        format: opts.format || 'png',
        scale: opts.scale || 2,
        set: this._setKey || 'v1',
      };
      const r = await fetch(`/api/export/${encodeURIComponent(this._company)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const job = await r.json();
      if (!r.ok) throw new Error(job.error || `export ${r.status}`);
      await this._pollExport(job.job_id);
    } catch (e) {
      this._setStatus('导出失败');
      alert('导出失败: ' + e.message);
    }
  },

  async _pollExport(jobId) {
    for (let i = 0; i < 80; i += 1) {
      await new Promise(resolve => setTimeout(resolve, 800));
      const r = await fetch(`/api/export/${encodeURIComponent(this._company)}/jobs/${encodeURIComponent(jobId)}`);
      const job = await r.json();
      if (!r.ok) throw new Error(job.error || `job ${r.status}`);
      if (job.status === 'done') {
        this._setStatus('导出完成');
        window.open(job.download_url, '_blank');
        return;
      }
      if (job.status === 'failed') throw new Error(job.error || '导出任务失败');
      this._setStatus(`导出中 ${i + 1}`);
    }
    throw new Error('导出超时');
  },

  _setStatus(text) {
    const el = document.getElementById('layout-status');
    if (el) el.textContent = text;
  },

  _esc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  },

  _escAttr(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;');
  },
};

document.addEventListener('DOMContentLoaded', () => LayoutApp.init());
