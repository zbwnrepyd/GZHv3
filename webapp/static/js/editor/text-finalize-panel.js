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
  _layoutCopyButtonBound: false,
  _layoutCopyGenerating: false,
  _cardSetKey: '',

  async init(company) {
    const sameCompany = this._company === company;
    this._company = company;
    if (!sameCompany) this._activeCardId = null;
    await Promise.all([this._loadCards(), this._loadFields()]);
    this._render();
    this._loaded = true;
  },

  async _loadCards() {
    try {
      const sk = EditorApp.currentSetKey || 'v4';
      this._cardSetKey = sk;
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
      this._syncLayoutCopyButton();
      return;
    }

    // 默认选中第一张卡片
    if (!this._activeCardId || !this._cards.find(c => c.card_id === this._activeCardId)) {
      this._activeCardId = this._cards[0].card_id;
    }

    const readiness = this._layoutCopyReadiness();
    const confirmedCount = readiness.confirmedCount;
    const totalCount = readiness.totalCount;

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
    this._bindLayoutCopyButton();
    this._syncLayoutCopyButton();
    this._bindRowEvents();
  },

  _bindLayoutCopyButton() {
    if (this._layoutCopyButtonBound) return;
    const btn = document.getElementById('tf-btn-generate-layout-copy');
    if (!btn) return;
    btn.addEventListener('click', () => this._generateLayoutCopy());
    this._layoutCopyButtonBound = true;
  },

  _layoutCopyReadiness() {
    const visibleKeys = this._visibleFieldKeys();
    const confirmedCount = visibleKeys.filter(k => (this._fieldsByKey[k] || {}).status === 'confirmed').length;
    const totalCount = visibleKeys.length;
    return {
      confirmedCount,
      totalCount,
      allConfirmed: totalCount > 0 && confirmedCount === totalCount,
    };
  },

  _syncLayoutCopyButton() {
    this._bindLayoutCopyButton();
    const btn = document.getElementById('tf-btn-generate-layout-copy');
    if (!btn) return;
    const readiness = this._layoutCopyReadiness();
    btn.disabled = this._layoutCopyGenerating;
    btn.textContent = readiness.allConfirmed ? '生成排版文案' : '等待文字定稿';
    btn.title = readiness.totalCount
      ? `${readiness.confirmedCount}/${readiness.totalCount} 已定稿，全部完成后可生成排版文案`
      : '点击后会先检查当前套卡文字定稿状态';
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

  _visibleFieldKeys() {
    const keys = [];
    const seen = new Set();
    (this._cards || []).forEach(card => {
      (card.items || []).forEach(item => {
        if (item.item_type !== 'field') return;
        const key = item.item_key;
        if (!key || seen.has(key)) return;
        if (!this._hasUsableField(key)) return;
        seen.add(key);
        keys.push(key);
      });
    });
    return keys;
  },

  _bestValueForField(fieldKey) {
    const f = this._fieldsByKey[fieldKey] || {};
    if (this._isUsableValue(f.final_value)) return String(f.final_value).trim();
    const versions = f.versions || {};
    for (const ver of ['standard', 'business', 'spread']) {
      if (this._isUsableValue(versions[ver])) return String(versions[ver]).trim();
    }
    const any = Object.values(versions).find(v => this._isUsableValue(v));
    return any ? String(any).trim() : '';
  },

  _isUsableValue(value) {
    if (value === null || value === undefined) return false;
    const s = String(value).trim();
    return !['', '暂缺', '待研究数据', 'None', 'none', 'null', 'NULL', '[]', '{}'].includes(s);
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
        await this._loadFields();
        await EditorApp.loadStatus?.();
        textarea.classList.remove('dirty');
        this._render();
      }
    } catch (e) { /* non-blocking */ }
  },

  async _confirmAll() {
    if (!confirm('确定将所有已填写的字段标记为已定稿？')) return;
    try {
      const fieldValues = {};
      this._visibleFieldKeys().forEach(key => {
        const value = this._bestValueForField(key);
        if (value) fieldValues[key] = value;
      });
      document.querySelectorAll('.tf-final-input').forEach(ta => {
        const key = ta.dataset.field;
        if (key && ta.value.trim()) fieldValues[key] = ta.value.trim();
      });
      await fetch(`/api/fields/${encodeURIComponent(this._company)}/confirm`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ field_values: fieldValues }),
      });
      await this._loadFields();
      await EditorApp.loadStatus?.();
      this._render();
    } catch (e) { alert('保存失败: ' + e.message); }
  },

  async _generateLayoutCopy() {
    const btn = document.getElementById('tf-btn-generate-layout-copy');
    if (!btn || this._layoutCopyGenerating) return;
    this._company = this._company || EditorApp.companyName || '';
    if (!this._company) return;
    const original = btn.textContent;
    this._layoutCopyGenerating = true;
    btn.disabled = true;
    btn.textContent = '生成中...';
    this._openLayoutCopyModal();
    this._setLayoutCopyStep('check', 'active', '正在检查当前套卡字段');
    this._setLayoutCopyMessage('正在检查文字定稿状态。');
    try {
      const sk = EditorApp.currentSetKey || 'v4';
      if (this._cardSetKey !== sk || !this._cards.length || !Object.keys(this._fieldsByKey).length) {
        await Promise.all([this._loadCards(), this._loadFields()]);
      }
      const readiness = this._layoutCopyReadiness();
      if (!readiness.allConfirmed) {
        this._setLayoutCopyStep('check', 'error', `${readiness.confirmedCount}/${readiness.totalCount} 已定稿`);
        this._setLayoutCopyMessage('文字定稿尚未全部完成，生成已停止。请先完成所有当前套卡字段定稿。', true);
        this._syncLayoutCopyButton();
        return;
      }
      this._setLayoutCopyStep('check', 'done', `${readiness.totalCount}/${readiness.totalCount} 已定稿`);
      this._setLayoutCopyStep('compose', 'active', '服务端正在串联每页事实');
      this._setLayoutCopyMessage('正在调用 AI 生成每页三段文案。当前后端是单次请求，细分进度将在请求返回后更新。');
      const r = await fetch(`/api/fields/${encodeURIComponent(this._company)}/layout-copy?set=${encodeURIComponent(sk)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ card_set_key: sk }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      this._setLayoutCopyStep('compose', 'done', '已生成三段文案');
      this._setLayoutCopyStep('write', 'done', `已写入 ${data.cards?.length || 0} 页`);
      this._setLayoutCopyStep('done', 'done', '可进入排版中心');
      this._setLayoutCopyMessage(`已生成 ${data.cards?.length || 0} 页排版文案，并写入排版中心。`);
      this._showLayoutCopyGoAction();
    } catch (e) {
      this._setLayoutCopyStep('compose', 'error', '生成失败');
      this._setLayoutCopyMessage('生成失败: ' + e.message, true);
    } finally {
      this._layoutCopyGenerating = false;
      btn.textContent = original;
      this._syncLayoutCopyButton();
    }
  },

  _openLayoutCopyModal() {
    const modal = document.getElementById('layout-copy-progress-modal');
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.querySelectorAll('[data-layout-copy-close]').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.addEventListener('click', () => modal.classList.add('hidden'));
      btn.dataset.bound = '1';
    });
    document.getElementById('layout-copy-progress-go')?.classList.add('hidden');
    ['check', 'compose', 'write', 'done'].forEach(step => {
      this._setLayoutCopyStep(step, 'pending', '等待开始');
    });
  },

  _setLayoutCopyStep(step, state, detail) {
    const item = document.querySelector(`#layout-copy-progress-modal [data-step="${step}"]`);
    if (!item) return;
    item.classList.remove('pending', 'active', 'done', 'error');
    item.classList.add(state);
    const small = item.querySelector('small');
    if (small) small.textContent = detail || '';
  },

  _setLayoutCopyMessage(message, isError = false) {
    const el = document.getElementById('layout-copy-progress-message');
    if (!el) return;
    el.textContent = message;
    el.classList.toggle('error', Boolean(isError));
  },

  _showLayoutCopyGoAction() {
    const go = document.getElementById('layout-copy-progress-go');
    const layout = document.getElementById('btn-go-layout');
    if (!go || !layout) return;
    go.href = layout.href || '#';
    go.classList.remove('hidden');
  },

  _esc(s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
  _escAttr(s) { return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
};

document.addEventListener('DOMContentLoaded', () => TextFinalizePanel._bindLayoutCopyButton());
