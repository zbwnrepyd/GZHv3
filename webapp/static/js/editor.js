const SLOT_LABELS = {
  logo: 'Logo',
  website_screenshot: '官网截图',
  founder_photo: '创始人照片',
  office: '办公室或地图',
  product_main: '主产品截图',
  products_other: '其他产品截图',
  competitors: '竞品截图',
  competitors_logo_strip: '三个竞品 Logo 横排图',
  chart_competitive: 'AI 创业公司竞争格局图',
  chart_ecosystem: 'AI 产业链生态位图',
  flywheel: '飞轮图',
  timeline: '时间线图',
};

const SLOT_ORDER = ['logo', 'website_screenshot', 'founder_photo', 'product_main', 'competitors', 'competitors_logo_strip', 'chart_competitive', 'chart_ecosystem', 'flywheel'];
const DEFAULT_CARD_SET_KEY = 'v4';

const EditorApp = {
  companyName: '',
  currentSetKey: DEFAULT_CARD_SET_KEY,
  _cardSets: [],
  currentSection: 'card-settings',
  _imageIframeLoaded: false,
  _slots: null,
  _activeSlot: null,

  async init() {
    const params = new URLSearchParams(window.location.search);
    this.companyName = params.get('company') || '';
    this.currentSetKey = params.get('set') || DEFAULT_CARD_SET_KEY;
    this.bindEvents();
    if (!this.companyName) {
      document.getElementById('editor-company-label').textContent = '请从研究台选择公司进入定稿台';
      return;
    }

    document.getElementById('editor-company-label').textContent = `定稿台 · ${this.companyName}`;

    const delBtn = document.getElementById('btn-delete-company');
    if (delBtn) {
      delBtn.classList.remove('hidden');
      delBtn.addEventListener('click', () => this.deleteCompany());
    }

    await this.loadCardSets();
    await this.loadStatus();
    this.switchSection('card-settings');
  },

  /* ── 套卡选择器 ── */

  async loadCardSets() {
    try {
      this._cardSets = await API.getCardSets();
    } catch {
      this._cardSets = [
        { set_key: 'v1', display_name: '套卡1 · 经典8张', spec_version: 'v1', card_count: 8, is_system: 1 },
      ];
    }
    this.renderCardSetSelector();
  },

  renderCardSetSelector() {
    const container = document.getElementById('card-set-selector');
    if (!container) return;

    container.innerHTML = this._cardSets.map(s => {
      const active = s.set_key === this.currentSetKey ? ' active' : '';
      const delBtn = s.is_system ? '' : `<span class="cs-tab-del" data-set="${s.set_key}">&times;</span>`;
      return `<span class="cs-tab${active}" data-set="${s.set_key}">${this._esc(s.display_name)}${delBtn}</span>`;
    }).join('') + `<span class="cs-tab cs-tab-add" id="cs-tab-add">+ 新建套卡</span>`;

    container.querySelectorAll('.cs-tab[data-set]').forEach(tab => {
      tab.addEventListener('click', async () => {
        const setKey = tab.dataset.set;
        if (setKey === this.currentSetKey) return;
        await this.switchCardSet(setKey);
      });
    });
    container.querySelectorAll('.cs-tab-del').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await this.deleteCardSet(btn.dataset.set);
      });
    });
    const addBtn = document.getElementById('cs-tab-add');
    if (addBtn) addBtn.addEventListener('click', () => this.showNewCardSetModal());
  },

  getCardCount(setKey = this.currentSetKey) {
    const cardSet = (this._cardSets || []).find(s => s.set_key === setKey);
    const count = Number(cardSet && cardSet.card_count);
    if (count > 0) return count;
    if (setKey === 'v2') return 7;
    if (setKey === 'v4') return 7;
    return 8;
  },

  async switchCardSet(setKey) {
    // 自动初始化编排结构
    try {
      await API.initCompanySet(this.companyName, setKey);
    } catch { /* 已存在则跳过 */ }
    this.currentSetKey = setKey;
    this.renderCardSetSelector();
    await this.loadStatus();
    // 更新排版中心链接
    const btnLayout = document.getElementById('btn-go-layout');
    if (btnLayout) btnLayout.href = `/layout?company=${encodeURIComponent(this.companyName)}&set=${setKey}`;
    // 刷新当前面板
    if (this.currentSection === 'card-settings') {
      CardSettingsPanel._loaded = false;  // force reload
      CardSettingsPanel.init(this.companyName);
    }
    if (this.currentSection === 'text-finalize') {
      TextFinalizePanel._loaded = false;
      TextFinalizePanel.init(this.companyName);
    }
  },

  async showNewCardSetModal() {
    const name = prompt('新建套卡名称：', '我的套卡');
    if (!name || !name.trim()) return;
    const spec = confirm('基于 v2 规格（7张）？\n点"确定"=v2（7张），点"取消"=v1（8张）') ? 'v2' : 'v1';
    try {
      const set = await API.createCardSet(name.trim(), spec);
      await API.initCompanySet(this.companyName, set.set_key);
      await this.loadCardSets();
      await this.switchCardSet(set.set_key);
    } catch (e) {
      alert('创建套卡失败: ' + e.message);
    }
  },

  async deleteCardSet(setKey) {
    const set = this._cardSets.find(s => s.set_key === setKey);
    if (!set) return;
    if (set.is_system) return alert('内置套卡不可删除。');
    if (!confirm(`删除套卡「${set.display_name}」？\n\n将同时删除该公司在此套卡中所有已确认内容。此操作不可撤销。`)) return;
    try {
      await API.deleteCompanySetData(this.companyName, setKey);
      await API.deleteCardSet(setKey);
      await this.loadCardSets();
      if (this.currentSetKey === setKey) {
        this.currentSetKey = DEFAULT_CARD_SET_KEY;
        await this.switchCardSet(DEFAULT_CARD_SET_KEY);
      } else {
        this.renderCardSetSelector();
      }
    } catch (e) {
      alert('删除失败: ' + e.message);
    }
  },

  bindEvents() {
    document.querySelectorAll('.accordion-header').forEach(header => {
      header.addEventListener('click', () => {
        this.switchSection(header.dataset.section);
      });
    });

    document.getElementById('btn-recollect-editor')?.addEventListener('click', () => this.recollectAssets());

  },

  /* ── 手风琴切换 ── */

  switchSection(section) {
    this.currentSection = section;

    document.querySelectorAll('.accordion-header').forEach(h => {
      h.classList.toggle('open', h.dataset.section === section);
    });
    document.querySelectorAll('.accordion-body').forEach(b => {
      if (b.dataset.section === 'card-settings' || b.dataset.section === 'text-finalize') {
        b.classList.remove('open');
      } else {
        b.classList.toggle('open', b.dataset.section === section);
      }
    });

    const modeHandlers = {
      'image':          () => { this.showImageMode(); },
      'card-settings':  () => { this.showCardSettingsMode(); CardSettingsPanel.init(this.companyName); },
      'text-finalize':  () => { this.showTextFinalizeMode(); TextFinalizePanel.init(this.companyName); },
      'db-fields':      () => { this.showDbFieldsMode(); DbFieldsPanel.init(this.companyName); },
    };
    const handler = modeHandlers[section];
    if (handler) handler();
  },

  /* ── 模式切换 ── */

  _OVERLAY_IDS: ['image-studio-frame', 'card-settings-mode', 'text-finalize-mode', 'db-fields-mode'],

  _closeAllOverlays() {
    this._OVERLAY_IDS.forEach(id => document.getElementById(id).classList.remove('open'));
  },

  _hidePanesShowOverlay(overlayId) {
    this._closeAllOverlays();
    document.getElementById(overlayId).classList.add('open');
  },

  showImageMode() {
    this._hidePanesShowOverlay('image-studio-frame');

    if (!this._imageIframeLoaded && this.companyName) {
      const iframe = document.getElementById('image-studio-iframe');
      const slot = this._activeSlot || '';
      iframe.src = `/image-studio/?company=${encodeURIComponent(this.companyName)}&embed=1&slot=${encodeURIComponent(slot)}&set=${this.currentSetKey}`;
      this._imageIframeLoaded = true;
    }

    this.loadImageSlots();
  },

  showCardSettingsMode() {
    this._hidePanesShowOverlay('card-settings-mode');
  },

  showTextFinalizeMode() {
    this._hidePanesShowOverlay('text-finalize-mode');
  },

  showDbFieldsMode() {
    this._hidePanesShowOverlay('db-fields-mode');
  },

  /* ── 图片槽位列表 ── */

  async loadImageSlots() {
    if (this._slots) {
      this.renderImageSlots();
      return;
    }
    try {
      const resp = await fetch(`/api/image-studio/${encodeURIComponent(this.companyName)}`);
      if (resp.ok) {
        const data = await resp.json();
        this._slots = data.slots || [];
        this.renderImageSlots();
      }
    } catch {
      // 静默
    }
  },

  renderImageSlots() {
    const container = document.getElementById('image-slot-list');
    if (!container || !this._slots) return;

    container.innerHTML = this._slots.map(s => {
      const isSvgSlot = s.asset_key === 'flywheel' || s.asset_key === 'timeline';
      const thumbHtml = s.local_path
        ? `<img src="${this._esc(s.local_path)}" alt="">`
        : `<div class="slot-thumb-small">${isSvgSlot ? '&#9881;' : '&#128247;'}</div>`;

      let meta;
      if (isSvgSlot) {
        meta = s.status === 'ready' ? 'SVG信息图 · 已就绪' : 'SVG信息图 · 待生成';
      } else {
        meta = s.status === 'ready' ? '已就绪' : '待配图';
        if (s.variant_count > 0) meta += ` · ${s.variant_count}变体`;
      }

      const activeCls = this._activeSlot === s.asset_key ? ' active' : '';

      return `
        <div class="image-slot-item${activeCls}" data-slot="${s.asset_key}">
          <div class="slot-thumb-small">${thumbHtml}</div>
          <div class="slot-info-small">
            <span class="slot-label-small">${SLOT_LABELS[s.asset_key] || s.asset_key}</span>
            <span class="slot-meta-small">${meta}</span>
          </div>
          <span class="slot-dot ${s.status}"></span>
        </div>
      `;
    }).join('');

    container.querySelectorAll('.image-slot-item').forEach(item => {
      item.addEventListener('click', () => {
        const slot = item.dataset.slot;
        this._activeSlot = slot;
        this.renderImageSlots();
        // 通知 iframe 切换槽位
        const iframe = document.getElementById('image-studio-iframe');
        iframe.src = `/image-studio/?company=${encodeURIComponent(this.companyName)}&embed=1&slot=${encodeURIComponent(slot)}&set=${this.currentSetKey}`;
      });
    });
  },

  async recollectAssets() {
    const btn = document.getElementById('btn-recollect-editor');
    if (btn) { btn.disabled = true; btn.textContent = '采集中...'; }
    try {
      const r = await fetch(`/api/assets/collect/${encodeURIComponent(this.companyName)}`, { method: 'POST' });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      this._slots = null;
      await this.loadImageSlots();
      // 刷新 iframe 中的 image-studio
      const iframe = document.getElementById('image-studio-iframe');
      if (iframe) iframe.src = iframe.src;
    } catch (e) {
      alert('采集失败: ' + e.message);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '重新采集图片'; }
    }
  },

  /* ── 状态 ── */

  async loadStatus() {
    try {
      const status = await API.getFinalStatus(this.companyName, this.currentSetKey);
      ConfirmManager.setConfirmed(status.confirmed || []);
    } catch {
      ConfirmManager.setConfirmed([]);
    }
  },


  async deleteCompany() {
    if (!this.companyName) return;
    const confirmed = confirm(
      `确定删除「${this.companyName}」的全部数据？\n\n` +
      `包括：研究记录、定稿内容、图片资产、图片变体\n` +
      `此操作不可恢复。`
    );
    if (!confirmed) return;

    const doubleConfirm = confirm('再次确认：输入"删除"或点确定继续，点取消放弃。');
    if (!doubleConfirm) return;

    try {
      const r = await fetch(`/api/research/${encodeURIComponent(this.companyName)}`, { method: 'DELETE' });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      alert(`已删除「${this.companyName}」。\n\n` +
        `研究记录: ${data.deleted.research} 条\n` +
        `研究任务: ${data.deleted.research_jobs} 条\n` +
        `定稿内容: ${data.deleted.final_content} 条\n` +
        `图片变体: ${data.deleted.image_variants} 条\n` +
        `资产记录: ${data.deleted.company_assets} 条\n` +
        `图片目录: ${data.deleted.images_dir}`
      );
      window.location.href = '/';
    } catch (e) {
      alert('删除失败: ' + e.message);
    }
  },

  _esc(s) {
    return String(s || '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
    }[ch]));
  },
};

document.addEventListener('DOMContentLoaded', () => EditorApp.init());
