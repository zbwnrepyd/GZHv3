/* text-finalize-panel.js — 文字定稿面板
   按卡片组织：加载卡片编排 → 每张卡片显示其包含的字段 → 三版本对比 → 点击采用 → 编辑定稿 */

const VERSION_LABELS_TF = { standard: '标准版', business: '商业版', spread: '传播版' };

// Confidence level badge config
const CONFIDENCE_BADGES = {
  verified:    { label: '✓ 已验证',   css: 'badge-verified' },
  estimated:   { label: '≈ 估算',     css: 'badge-estimated' },
  benchmark:   { label: 'ⓘ 行业基准', css: 'badge-benchmark' },
  unavailable: { label: '— 未公开',   css: 'badge-unavailable' },
};

function renderConfidenceBadge(confidenceLevel) {
  const cfg = CONFIDENCE_BADGES[confidenceLevel];
  if (!cfg) return '';
  return '<span class="confidence-badge ' + cfg.css + '">' + cfg.label + '</span>';
}

const TextFinalizePanel = {
  _company: '',
  _cards: [],
  _fieldsByKey: {},       // field_key → { label, versions, final_value, status }
  _activeCardId: null,

  async init(company) {
    if (this._loaded && this._company === company) return;
    this._company = company;
    this._activeCardId = null;
    await Promise.all([this._loadCards(), this._loadFields()]);
    this._render();
    this._loaded = true;
  },

  async _loadCards() {
    try {
      const sk = EditorApp.currentSetKey || 'v1';
      const r = await fetch(`/api/card-config/${encodeURIComponent(this._company)}?set=${sk}`);
      const d = await r.json();
      this._cards = (d.cards || []).filter(c => c.enabled !== false);
    } catch { this._cards = []; }
  },

  async _loadFields() {
    this._fieldsByKey = {};
    try {
      const r = await fetch(`/api/fields/${encodeURIComponent(this._company)}`);
      const d = await r.json();
      (d.groups || []).forEach(g => {
        (g.fields || []).forEach(f => {
          this._fieldsByKey[f.field_key] = {
            label: f.field_label || f.field_key,
            versions: f.versions || {},
            final_value: f.final_value || '',
            status: f.status || 'draft',
            confidence_level: f.confidence_level || '',
          };
        });
      });
    } catch { /* empty */ }
  },

  _render() {
    const root = document.getElementById('text-finalize-mode-content');
    if (!root) return;

    if (!this._cards.length) {
      root.innerHTML = '<div class="tf-empty-state">暂无卡片编排数据，请先在「卡片设置」中配置卡片</div>';
      return;
    }

    // 默认选中第一张卡片
    if (!this._activeCardId || !this._cards.find(c => c.card_id === this._activeCardId)) {
      this._activeCardId = this._cards[0].card_id;
    }

    const confirmedCount = Object.values(this._fieldsByKey).filter(f => f.status === 'confirmed').length;
    const totalCount = Object.keys(this._fieldsByKey).length;

    root.innerHTML = `
      <div class="tf-top-bar">
        <span class="tf-progress">${confirmedCount}/${totalCount} 已定稿</span>
        <button class="tf-btn-confirm-all" id="tf-btn-confirm-all">全部定稿</button>
      </div>
      <div class="tf-card-tabs">
        ${this._cards.map(c => this._cardTab(c)).join('')}
      </div>
      <div class="tf-card-content" id="tf-card-content">
        ${this._cardContent(this._activeCardId)}
      </div>
    `;

    document.getElementById('tf-btn-confirm-all')?.addEventListener('click', () => this._confirmAll());
    document.querySelectorAll('.tf-card-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        this._activeCardId = tab.dataset.cardId;
        this._render();
      });
    });
    this._bindRowEvents();
  },

  _cardTab(card) {
    const active = card.card_id === this._activeCardId ? ' active' : '';
    const items = card.items || [];
    const cardFields = items.filter(i => i.item_type === 'field');
    const fieldCount = cardFields.filter(i => this._hasUsableField(i.item_key)).length;
    const confirmed = cardFields.every(i => (this._fieldsByKey[i.item_key] || {}).status === 'confirmed');
    const dot = cardFields.length ? (confirmed ? '·' : '○') : '';
    return `
      <button class="tf-card-tab${active}" data-card-id="${card.card_id}">
        <span class="tf-card-tab-idx">${card.card_index || ''}</span>
        <span class="tf-card-tab-title">${this._esc(card.card_title)}</span>
        <span class="tf-card-tab-meta">${fieldCount}项 ${dot}</span>
      </button>`;
  },

  _cardContent(cardId) {
    const card = this._cards.find(c => c.card_id === cardId);
    if (!card) return '<p class="tf-empty-hint">未找到卡片</p>';

    const items = card.items || [];
    const fieldItems = items.filter(i => i.item_type === 'field');
    const usableItems = fieldItems.filter(i => this._hasUsableField(i.item_key));
    const pendingItems = fieldItems.filter(i => !this._hasUsableField(i.item_key) && this._fieldsByKey[i.item_key]);

    if (!fieldItems.length) {
      return `<div class="tf-card-empty">
        <p>这张卡片没有分配字段。</p>
        <p>请先在「卡片设置」中为「${this._esc(card.card_title)}」添加字段。</p>
      </div>`;
    }

    return `
      <div class="tf-card-header">
        <h3 class="tf-card-name">${this._esc(card.card_title)}</h3>
        <span class="tf-card-subtitle">${usableItems.length} 个可定稿字段${pendingItems.length ? ` · ${pendingItems.length} 个待补` : ''}</span>
      </div>
      <div class="tf-fields">
        ${usableItems.map(item => this._fieldCard(item, card)).join('')}
      </div>
      ${pendingItems.length ? this._pendingFieldsBlock(pendingItems) : ''}`;
  },

  _pendingFieldsBlock(items) {
    return `
      <details class="tf-pending-fields" open>
        <summary class="tf-pending-summary">待补字段 · ${items.length} 项</summary>
        <ul class="tf-pending-list">
          ${items.map(item => {
            const f = this._fieldsByKey[item.item_key] || {};
            return `<li class="tf-pending-row">
              <span class="tf-pending-label">${this._esc(f.label || item.item_key)}</span>
              <span class="tf-pending-hint">待研究数据</span>
            </li>`;
          }).join('')}
        </ul>
      </details>`;
  },

  _fieldCard(item, card) {
    const f = this._fieldsByKey[item.item_key];
    if (!f) return '';

    const versions = f.versions || {};
    const finalVal = f.final_value || '';
    const confirmed = f.status === 'confirmed';
    const hasVersions = Object.keys(versions).length > 0;
    const hasFinalValue = this._isUsableValue(finalVal);

    return `
      <div class="tf-field-card ${confirmed ? 'confirmed' : ''}" data-field="${item.item_key}">
        <div class="tf-field-head">
          <span class="tf-field-label">${this._esc(f.label)}</span>
          ${renderConfidenceBadge(f.confidence_level)}
          <span class="tf-field-role">${this._esc(item.display_role || 'body')}</span>
          <span class="tf-field-dot ${confirmed ? 'confirmed' : 'draft'}" title="${confirmed ? '已定稿' : '未定稿'}"></span>
        </div>

        ${hasVersions ? `
        <div class="tf-versions">
          ${Object.entries(versions).map(([ver, val]) => `
            <div class="tf-version-card" data-field="${item.item_key}" data-value="${this._escAttr(val)}"
                 title="点击采用${VERSION_LABELS_TF[ver] || ver}版本">
              <span class="tf-ver-tag">${VERSION_LABELS_TF[ver] || ver}</span>
              <p class="tf-ver-text">${this._esc(val)}</p>
            </div>
          `).join('')}
        </div>` : (hasFinalValue ? '' : '<p class="tf-empty-hint">暂无研究数据</p>')}

        <div class="tf-final-area">
          <textarea class="tf-final-input" data-field="${item.item_key}" rows="2"
            placeholder="输入定稿内容...">${this._esc(finalVal)}</textarea>
          <button class="tf-save-btn" data-field-key="${item.item_key}">保存</button>
        </div>
      </div>`;
  },

  _hasUsableField(fieldKey) {
    const f = this._fieldsByKey[fieldKey];
    if (!f) return false;
    if (this._isUsableValue(f.final_value)) return true;
    return Object.values(f.versions || {}).some(v => this._isUsableValue(v));
  },

  _isUsableValue(value) {
    if (value === null || value === undefined) return false;
    const s = String(value).trim();
    return !['', '暂缺', 'None', 'none', 'null', 'NULL', '[]', '{}'].includes(s);
  },

  _bindRowEvents() {
    document.querySelectorAll('.tf-version-card').forEach(card => {
      card.addEventListener('click', () => {
        const fieldKey = card.dataset.field;
        const value = card.dataset.value || '';
        const textarea = document.querySelector(`.tf-final-input[data-field="${fieldKey}"]`);
        if (textarea) { textarea.value = value; textarea.classList.add('dirty'); textarea.focus(); }
      });
    });
    document.querySelectorAll('.tf-save-btn').forEach(btn => {
      btn.addEventListener('click', () => this._saveField(btn.dataset.fieldKey));
    });
  },

  async _saveField(fieldKey) {
    const textarea = document.querySelector(`.tf-final-input[data-field="${fieldKey}"]`);
    if (!textarea) return;
    const value = textarea.value.trim();
    try {
      const r = await fetch(`/api/fields/${encodeURIComponent(this._company)}/${encodeURIComponent(fieldKey)}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ final_value: value, status: 'confirmed' }),
      });
      if (r.ok) {
        this._fieldsByKey[fieldKey].final_value = value;
        this._fieldsByKey[fieldKey].status = 'confirmed';
        textarea.classList.remove('dirty');
        this._render();
      }
    } catch (e) { /* non-blocking */ }
  },

  async _confirmAll() {
    if (!confirm('确定将所有已填写的字段标记为已定稿？')) return;
    try {
      const fieldValues = {};
      document.querySelectorAll('.tf-final-input').forEach(ta => {
        const key = ta.dataset.field;
        if (key && ta.value.trim()) fieldValues[key] = ta.value.trim();
      });
      await fetch(`/api/fields/${encodeURIComponent(this._company)}/confirm`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ field_values: fieldValues }),
      });
      await this._loadFields();
      this._render();
    } catch (e) { alert('保存失败: ' + e.message); }
  },

  _esc(s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
  _escAttr(s) { return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
};
