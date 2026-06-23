/* search-panel.js — 中栏：预览/搜索结果切换 + 工具栏 */
const SearchPanel = {
  _company: '',
  _assetKey: '',
  _currentQuery: '',
  _currentSource: 'pexels',
  _currentLang: 'en',
  _currentPage: 1,
  _totalResults: 0,
  _perPage: 9,
  _loading: false,
  _slotImage: '',
  _slotStatus: '',    // slot 状态：missing | failed | ready | ...
  _view: 'preview', // 'preview' | 'search'
  _container: null,
  _onFetch: null,     // callback(imageData) — 搜索结果被点击下载后
  _onRefresh: null,   // callback() — 变体列表刷新后（重采集等）
  _queries: [],
  _capturing: false,  // 是否正在采集中

  init(container, { onFetch, onRefresh }) {
    this._container = container;
    this._onFetch = onFetch;
    this._onRefresh = onRefresh;
    this._render();
  },

  setContext(company, assetKey) {
    this._company = company;
    this._assetKey = assetKey;
    this._currentPage = 1;
    this._totalResults = 0;
    this._slotImage = '';
    this._slotStatus = '';
    this._capturing = false;
    this._view = 'preview';
  },

  /* 外部调用：设置当前槽位已选图片。status 可选，传入 slot 状态用于 missing/failed 判断 */
  setSlotImage(localPath, status) {
    this._slotImage = localPath || '';
    if (status !== undefined) this._slotStatus = status;
    this._renderPreview();
  },

  /* 外部调用：右栏缩略图点击时在中间预览 */
  showPreviewImage(src) {
    this._slotImage = src;
    if (src) this._slotStatus = 'ready';  // 有候选图片时标记为 ready
    this._switchView('preview');
    this._renderPreview();
  },

  setQueries(queries) {
    this._queries = queries || [];
    // 预填搜索框为第一个查询词
    if (this._queries.length) {
      const q = this._queries[0];
      this._currentQuery = this._currentLang === 'zh' ? q.zh : q.en;
      const input = this._container?.querySelector('.search-input');
      if (input) input.value = this._currentQuery;
    }
  },

  search(query) {
    if (query !== undefined) this._currentQuery = query;
    this._currentPage = 1;
    this._doSearch();
  },

  /* ── Render ── */

  _render() {
    if (!this._container) return;
    this._container.innerHTML = `
      <!-- 预览切换按钮 -->
      <div class="preview-toggle-bar">
        <button class="toggle-btn active" data-view="preview">选定图片</button>
        <button class="toggle-btn" data-view="search">搜索结果</button>
      </div>

      <!-- 上部：预览区 -->
      <div class="preview-stage" id="preview-stage">
        <div class="preview-empty">
          <div class="empty-icon">&#128247;</div>
          <p>未选择图片</p>
        </div>
      </div>

      <!-- 上部：搜索结果区 -->
      <div class="search-results-area hidden" id="search-results-area">
        <div class="results-grid" id="results-grid"></div>
        <div class="results-pagination" id="results-pagination"></div>
      </div>

      <!-- 下部：工具栏（一级：预览/重采集/上传/确认；高级折叠其余） -->
      <div class="toolbar-section" id="toolbar-section">
        <div class="toolbar-primary-row">
          <button class="btn-recollect-all">全部重新采集</button>
          <button class="btn-recollect-slot">当页重新采集</button>
          <button class="btn-small" id="btn-upload">上传图片</button>
          <button class="btn-small toggle-advanced" id="btn-toggle-advanced">高级 ▸</button>
        </div>
        <div class="toolbar-advanced-row hidden" id="toolbar-advanced">
          <div class="toolbar-search-row">
            <input class="search-input" type="text" placeholder="搜索关键词...">
            <select class="engine-select">
              <option value="pexels">Pexels</option>
              <option value="unsplash">Unsplash</option>
              <option value="tavily">Tavily</option>
            </select>
            <button class="btn-search">搜索</button>
          </div>
          <div class="toolbar-actions-row">
            <input class="ai-prompt-input" type="text" placeholder="AI 生图 prompt...">
            <button class="btn-small accent" id="btn-ai-gen">生成</button>
            <input class="url-input" type="text" placeholder="图片 URL...">
            <button class="btn-small" id="btn-url-fetch">下载</button>
            <button class="btn-small" id="btn-rescore">重新评分</button>
          </div>
        </div>
        <button class="btn-generate-map hidden" id="btn-generate-map">生成地图</button>
        <input type="file" accept="image/*" class="file-input-hidden" id="file-upload-input">
      </div>
    `;

    this._bindEvents();
    this._renderPreview();
    this._updateToolbarForSlot();
  },

  _bindEvents() {
    if (!this._container) return;

    // 切换按钮
    this._container.querySelectorAll('.toggle-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        this._switchView(btn.dataset.view);
      });
    });

    // 搜索
    this._container.querySelector('.btn-search').addEventListener('click', () => {
      this._currentQuery = this._container.querySelector('.search-input').value;
      this.search();
    });
    this._container.querySelector('.search-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        this._currentQuery = e.target.value;
        this.search();
      }
    });
    this._container.querySelector('.engine-select').addEventListener('change', (e) => {
      this._currentSource = e.target.value;
      if (this._currentSource === 'unsplash') this._currentLang = 'en';
      else if (this._currentSource === 'pexels') this._currentLang = 'zh';
      if (this._queries.length) {
        const q = this._queries[0];
        this._currentQuery = this._currentLang === 'zh' ? q.zh : q.en;
        this._container.querySelector('.search-input').value = this._currentQuery;
      }
      this.search();
    });

    // 重采集
    this._container.querySelector('.btn-recollect-all').addEventListener('click', () => this._recollectAll());
    this._container.querySelector('.btn-recollect-slot').addEventListener('click', () => this._recollectSlot());

    // AI 生图
    this._container.querySelector('#btn-ai-gen').addEventListener('click', () => {
      const prompt = this._container.querySelector('.ai-prompt-input').value.trim();
      if (prompt) this._onAiGenerate(prompt);
    });
    this._container.querySelector('.ai-prompt-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const prompt = e.target.value.trim();
        if (prompt) this._onAiGenerate(prompt);
      }
    });

    // 地图生成
    this._container.querySelector('#btn-generate-map').addEventListener('click', () => this._onGenerateMap());

    // 重新评分
    this._container.querySelector('#btn-rescore').addEventListener('click', () => this._onRescore());

    // 高级面板切换
    this._container.querySelector('#btn-toggle-advanced').addEventListener('click', () => {
      const advanced = this._container.querySelector('#toolbar-advanced');
      const btn = this._container.querySelector('#btn-toggle-advanced');
      advanced.classList.toggle('hidden');
      btn.textContent = advanced.classList.contains('hidden') ? '高级 ▸' : '高级 ▾';
    });

    // 上传
    this._container.querySelector('#btn-upload').addEventListener('click', () => {
      this._container.querySelector('#file-upload-input').click();
    });
    this._container.querySelector('#file-upload-input').addEventListener('change', (e) => {
      if (e.target.files[0]) this._importFile(e.target.files[0]);
    });

    // URL 导入
    this._container.querySelector('#btn-url-fetch').addEventListener('click', () => {
      const url = this._container.querySelector('.url-input').value.trim();
      if (url) this._importUrl(url);
    });
    this._container.querySelector('.url-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const url = e.target.value.trim();
        if (url) this._importUrl(url);
      }
    });
  },

  _switchView(view) {
    this._view = view;
    const previewStage = document.getElementById('preview-stage');
    const searchArea = document.getElementById('search-results-area');
    const btns = this._container.querySelectorAll('.toggle-btn');

    btns.forEach(b => b.classList.toggle('active', b.dataset.view === view));

    if (view === 'preview') {
      previewStage?.classList.remove('hidden');
      searchArea?.classList.add('hidden');
    } else {
      previewStage?.classList.add('hidden');
      searchArea?.classList.remove('hidden');
    }
  },

  _renderPreview() {
    const stage = document.getElementById('preview-stage');
    if (!stage) return;
    if (this._slotImage) {
      stage.innerHTML = `<img src="${this._escape(this._slotImage)}" alt="选定预览" onerror="this.parentElement.innerHTML='<div class=preview-empty><div class=empty-icon>&#9888;</div><p>图片加载失败</p></div>'">`;
    } else if ((this._slotStatus === 'missing' || this._slotStatus === 'failed') && this._assetKey) {
      const label = (window.DEMAND_LABELS && window.DEMAND_LABELS[this._assetKey]) || this._assetKey;
      const reason = this._slotStatus === 'failed' ? '采集失败，可重试' : '暂未采集';
      const icon = this._slotStatus === 'failed' ? '&#9888;' : '&#128247;';
      const btnDisabled = this._capturing ? 'disabled' : '';
      const btnText = this._capturing ? '采集中...' : '立即采集';
      stage.innerHTML = `
        <div class="preview-empty">
          <div class="empty-icon">${icon}</div>
          <p>${this._escape(label)} · ${reason}</p>
          <button class="btn-capture-now" id="btn-capture-now" ${btnDisabled}>${btnText}</button>
        </div>`;
      const btn = stage.querySelector('#btn-capture-now');
      if (btn) {
        btn.addEventListener('click', () => this._captureScreenshot());
      }
    } else {
      stage.innerHTML = `<div class="preview-empty"><div class="empty-icon">&#128247;</div><p>未选择图片</p></div>`;
    }
  },

  _updateToolbarForSlot() {
    const isOffice = this._assetKey === 'office';
    const mapBtn = document.getElementById('btn-generate-map');
    if (mapBtn) mapBtn.classList.toggle('hidden', !isOffice);
  },

  /* ── 搜索 ── */

  _doSearch() {
    if (this._loading) return;
    if (!this._currentQuery.trim()) return;

    this._loading = true;
    this._switchView('search');
    this._renderGridLoading();

    StudioAPI.search(this._company, this._assetKey, {
      query: this._currentQuery,
      source: this._currentSource,
      lang: this._currentLang,
      page: this._currentPage,
      perPage: this._perPage,
    }).then(data => {
      this._totalResults = data.total || 0;
      this._renderGrid(data.results || []);
      this._renderPagination();
      this._loading = false;
    }).catch(err => {
      this._showGridEmpty(err.message);
      this._loading = false;
    });
  },

  _renderGrid(results) {
    const grid = document.getElementById('results-grid');
    if (!grid) return;
    if (!results.length) {
      grid.innerHTML = `<div class="empty-state"><div class="empty-icon">&#128269;</div><p>没有找到相关图片</p></div>`;
      return;
    }
    grid.innerHTML = results.map(img => `
      <div class="result-card" data-json="${this._escape(JSON.stringify(img))}">
        <img src="${this._escape(img.thumbnail_url || img.full_url)}" alt="" loading="lazy"
             onerror="this.parentElement.style.opacity='0.5'">
        <div class="result-overlay">
          <span>${this._escape(img.author || '')}</span>
          <span class="result-source-badge">${img.source === 'pexels' ? 'P' : img.source === 'unsplash' ? 'U' : 'T'}</span>
        </div>
        ${img.source === 'tavily' ? '<div class="tavily-warn">&#9888; 版权未核实</div>' : ''}
      </div>
    `).join('');

    grid.querySelectorAll('.result-card').forEach(card => {
      card.addEventListener('click', () => {
        try {
          const data = JSON.parse(card.dataset.json);
          if (this._onFetch) this._onFetch(data);
        } catch { /* ignore */ }
      });
    });
  },

  _renderGridLoading() {
    const grid = document.getElementById('results-grid');
    if (grid) grid.innerHTML = `<div class="empty-state"><div class="empty-icon">&#8987;</div><p>搜索中...</p></div>`;
  },

  _showGridEmpty(msg) {
    const grid = document.getElementById('results-grid');
    if (grid) grid.innerHTML = `<div class="empty-state"><div class="empty-icon">&#9888;</div><p>${this._escape(msg || '搜索失败')}</p></div>`;
  },

  _renderPagination() {
    const el = document.getElementById('results-pagination');
    if (!el) return;
    const totalPages = Math.max(1, Math.ceil(this._totalResults / this._perPage));
    el.innerHTML = `
      <button class="prev-btn" ${this._currentPage <= 1 ? 'disabled' : ''}>&#8592; 前一页</button>
      <span>第 ${this._currentPage} / ${totalPages} 页</span>
      <button class="next-btn" ${this._currentPage >= totalPages ? 'disabled' : ''}>下一页 &#8594;</button>
    `;
    el.querySelector('.prev-btn')?.addEventListener('click', () => {
      if (this._currentPage > 1) { this._currentPage--; this._doSearch(); }
    });
    el.querySelector('.next-btn')?.addEventListener('click', () => {
      const tp = Math.ceil(this._totalResults / this._perPage);
      if (this._currentPage < tp) { this._currentPage++; this._doSearch(); }
    });
  },

  /* ── 一键采集（empty state 按钮）── */

  async _captureScreenshot() {
    if (this._capturing) return;
    this._capturing = true;
    this._renderPreview();  // 按钮变 disabled

    try {
      const url = `/api/assets/collect/${encodeURIComponent(this._company)}?asset_key=${encodeURIComponent(this._assetKey)}`;
      const r = await fetch(url, { method: 'POST' });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);

      // 采集成功：更新状态，刷新变体列表和槽位
      this._slotStatus = 'ready';
      if (this._onRefresh) await this._onRefresh();
      // VariantSidebar._loadVariants 会自动预览已选中的变体
    } catch (e) {
      this._slotStatus = 'failed';
      this._renderPreview();  // 显示错误状态 + 重试按钮
      this._toast('采集失败: ' + e.message, 'error');
    } finally {
      this._capturing = false;
      // 如果采集成功，_onRefresh 中 VariantSidebar 会自动调用 showPreviewImage，
      // 此时 _slotImage 已设置，_renderPreview 会显示图片
      if (this._slotStatus === 'failed') {
        this._renderPreview();  // 确保显示重试按钮
      }
    }
  },

  /* ── 重采集 ── */

  async _recollectAll() {
    const btn = this._container?.querySelector('.btn-recollect-all');
    if (btn) { btn.disabled = true; btn.textContent = '采集中...'; }
    try {
      const r = await fetch(`/api/assets/collect/${encodeURIComponent(this._company)}`, { method: 'POST' });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      if (this._onRefresh) this._onRefresh();
      this._toast('全部重新采集完成');
    } catch (e) {
      this._toast('采集失败: ' + e.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '全部重新采集'; }
    }
  },

  async _recollectSlot() {
    const btn = this._container?.querySelector('.btn-recollect-slot');
    if (btn) { btn.disabled = true; btn.textContent = '采集中...'; }
    try {
      const url = `/api/assets/collect/${encodeURIComponent(this._company)}?asset_key=${encodeURIComponent(this._assetKey)}`;
      const r = await fetch(url, { method: 'POST' });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      this._slotStatus = 'ready';
      if (this._onRefresh) await this._onRefresh();
    } catch (e) {
      this._toast('采集失败: ' + e.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '当页重新采集'; }
    }
  },

  /* ── AI 生图 ── */

  async _onAiGenerate(prompt) {
    const btn = document.getElementById('btn-ai-gen');
    if (btn) { btn.disabled = true; btn.textContent = '生成中...'; }
    try {
      const result = await fetch('/api/generate-image', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt, company_name: this._company,
          field_name: this._assetKey, asset_key: this._assetKey,
        }),
      }).then(r => r.json());
      if (result.error) throw new Error(result.error);
      await StudioAPI.fetch(this._company, this._assetKey, {
        full_url: result.img_path, id: `ai_${Date.now()}`,
        source: 'api_generate', source_page: '',
        author: 'AI Generated', license: 'AI',
      });
      if (this._onRefresh) this._onRefresh();
      const input = this._container?.querySelector('.ai-prompt-input');
      if (input) input.value = '';
    } catch (e) {
      this._toast('AI 生成失败: ' + e.message, 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = '生成'; }
  },

  /* ── 地图生成 ── */

  async _onGenerateMap() {
    const btn = document.getElementById('btn-generate-map');
    if (btn) { btn.disabled = true; btn.textContent = '生成中...'; }
    try {
      const r = await fetch(
        `/api/image-studio/${encodeURIComponent(this._company)}/${encodeURIComponent(this._assetKey)}/generate-map`,
        { method: 'POST' }
      );
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
      if (this._onRefresh) this._onRefresh();
    } catch (e) {
      this._toast('地图生成失败: ' + e.message, 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = '生成地图'; }
  },

  /* ── 重新评分 ── */

  async _onRescore() {
    const btn = document.getElementById('btn-rescore');
    if (btn) { btn.disabled = true; btn.textContent = '评分中...'; }
    try {
      await StudioAPI.rescoreVariants(this._company, this._assetKey);
      if (this._onRefresh) this._onRefresh();
      this._toast('已重新评分并自动选优');
    } catch (e) {
      this._toast('重新评分失败: ' + e.message, 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = '重新评分'; }
  },

  /* ── 上传 / URL ── */

  async _importUrl(url) {
    const btn = document.getElementById('btn-url-fetch');
    if (btn) { btn.disabled = true; btn.textContent = '下载中...'; }
    try {
      await StudioAPI.importUrl(this._company, this._assetKey, url);
      const input = this._container?.querySelector('.url-input');
      if (input) input.value = '';
      if (this._onRefresh) this._onRefresh();
      this._toast('导入成功');
    } catch (e) {
      this._toast('导入失败: ' + e.message, 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = '下载'; }
  },

  async _importFile(file) {
    const btn = document.getElementById('btn-upload');
    if (btn) { btn.disabled = true; btn.textContent = '上传中...'; }
    try {
      await StudioAPI.importFile(this._company, this._assetKey, file);
      if (this._onRefresh) this._onRefresh();
      this._toast('上传成功');
    } catch (e) {
      this._toast('上传失败: ' + e.message, 'error');
    }
    if (btn) { btn.disabled = false; btn.textContent = '上传图片'; }
  },

  /* ── 隐藏/显示 (Logo / SVG 槽位) ── */

  /* Logo 只读：只显示预览图，无切换按钮、无搜索结果、无工具栏 */
  showPreviewOnly(imageSrc) {
    if (!this._container) return;
    this._container.querySelector('.preview-toggle-bar')?.classList.add('hidden');
    document.getElementById('search-results-area')?.classList.add('hidden');
    document.getElementById('toolbar-section')?.classList.add('hidden');
    const stage = document.getElementById('preview-stage');
    if (stage) {
      stage.classList.remove('hidden');
      if (imageSrc) {
        stage.innerHTML = `<img src="${this._escape(imageSrc)}" alt="Logo" onerror="this.parentElement.innerHTML='<div class=preview-empty><div class=empty-icon>&#127760;</div><p>Logo 加载失败</p></div>'">`;
      } else {
        stage.innerHTML = `<div class="preview-empty"><div class="empty-icon">&#127760;</div><p>暂未获取到 Logo</p></div>`;
      }
    }
  },

  hideAll() {
    if (!this._container) return;
    this._container.querySelector('.preview-toggle-bar')?.classList.add('hidden');
    document.getElementById('preview-stage')?.classList.add('hidden');
    document.getElementById('search-results-area')?.classList.add('hidden');
    document.getElementById('toolbar-section')?.classList.add('hidden');
  },

  showAll() {
    if (!this._container) return;
    this._container.querySelector('.preview-toggle-bar')?.classList.remove('hidden');
    document.getElementById('toolbar-section')?.classList.remove('hidden');
    this._switchView(this._view);
    this._updateToolbarForSlot();
  },

  /* ── Toast ── */

  _toast(msg, type) {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();
    const el = document.createElement('div');
    el.className = 'toast' + (type === 'error' ? ' error' : '');
    el.textContent = msg;
    document.body.appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => {
      el.classList.remove('show');
      setTimeout(() => el.remove(), 200);
    }, 2500);
  },

  _escape(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },
};
