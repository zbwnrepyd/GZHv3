const CARD_COUNT = 8;
const SOURCE_LABELS = {
  scrapling_search: '开放网页搜索',
  tavily: 'Tavily 搜索',
  tavily_search: 'Tavily 搜索',
  tavily_extract: 'Tavily 深抓',
  official_site: '官网抓取',
  github: 'GitHub',
  youtube: 'YouTube',
  producthunt: 'Product Hunt',
  sec: 'SEC',
  openbb: 'OpenBB',
  companieshouse: 'Companies House',
  whatweb: 'WhatWeb',
  website: '官网抓取',
};
const SOURCE_ORDER = ['official_site', 'scrapling_search', 'github', 'youtube', 'producthunt', 'whatweb', 'sec', 'companieshouse', 'openbb', 'tavily_search', 'tavily_extract'];
const RESEARCH_OPTION_DEFAULTS = {
  scrapling_search: true,
  official_site: true,
  tavily_search: true,
  tavily_extract: true,
  github: true,
  producthunt: true,
  youtube: true,
  sec: true,
  companieshouse: true,
  openbb: true,
  whatweb: true,
  gap_refetch: true,
  document_chunking: true,
  context_packer: true,
  evidence_span_binding: true,
  image_collection: true,
};
const RESEARCH_PROGRESS_STEPS = [
  { id: 'start', label: '启动', percent: 5, matches: ['启动', '准备', '提交', '恢复'] },
  { id: 'collect', label: '信息采集', percent: 20, matches: ['采集', '官网抓取', 'Tavily', 'GitHub', 'YouTube'] },
  { id: 'analysis', label: '结构分析', percent: 45, matches: ['分析', 'L0', 'L1', 'L2', '清洗', '横纵', '商业结构'] },
  { id: 'extract', label: '字段提取', percent: 70, matches: ['L3', '字段', 'JSON修复'] },
  { id: 'enum', label: '枚举验证', percent: 82, matches: ['枚举', '投票', '验证', '规则'] },
  { id: 'persist', label: '入库图片', percent: 95, matches: ['写库', '写入', '图片', '候选图'] },
  { id: 'done', label: '完成', percent: 100, matches: ['完成'] },
];

const ResearchDesk = {
  pollTimer: null,
  activeJobId: null,
  pollInFlight: false,
  currentProgressPercent: 0,
  currentSources: {},
  companies: [],
  expandedCompany: '',
  detailsByCompany: {},

  init() {
    document.getElementById('btn-start-research').addEventListener('click', () => this.startResearch());
    document.getElementById('btn-stop-research').addEventListener('click', () => this.stopResearch());
    document.getElementById('btn-refresh-companies').addEventListener('click', () => this.loadCompanies());
    document.getElementById('btn-reset-research-options')?.addEventListener('click', () => this.resetResearchOptions());
    document.querySelectorAll('[data-research-option]').forEach(input => {
      input.addEventListener('change', () => this.saveResearchOptions());
    });
    document.getElementById('company-table-body').addEventListener('click', (event) => {
      const refillButton = event.target.closest('[data-refill-company]');
      if (refillButton) {
        this.refillResearch(refillButton.dataset.refillCompany, refillButton.dataset.refillUrl || '');
        return;
      }
      if (event.target.closest('a, button')) return;
      const row = event.target.closest('.company-row');
      if (!row) return;
      this.toggleCompanyDetails(decodeURIComponent(row.dataset.company));
    });
    this.loadResearchOptions();
    this.loadCompanies();
    this._restoreActiveJob();
  },

  loadResearchOptions() {
    let saved = {};
    try {
      saved = JSON.parse(localStorage.getItem('gzh2_research_options') || '{}') || {};
    } catch {
      saved = {};
    }
    const options = { ...RESEARCH_OPTION_DEFAULTS, ...saved };
    document.querySelectorAll('[data-research-option]').forEach(input => {
      const key = input.dataset.researchOption;
      input.checked = Boolean(options[key]);
    });
    this.updateResearchOptionsSummary();
  },

  collectResearchOptions() {
    const options = { ...RESEARCH_OPTION_DEFAULTS };
    document.querySelectorAll('[data-research-option]').forEach(input => {
      options[input.dataset.researchOption] = Boolean(input.checked);
    });
    return options;
  },

  saveResearchOptions() {
    const options = this.collectResearchOptions();
    localStorage.setItem('gzh2_research_options', JSON.stringify(options));
    this.updateResearchOptionsSummary();
  },

  resetResearchOptions() {
    localStorage.removeItem('gzh2_research_options');
    this.loadResearchOptions();
  },

  updateResearchOptionsSummary() {
    const el = document.getElementById('research-options-summary');
    if (!el) return;
    const options = this.collectResearchOptions();
    const enabled = Object.values(options).filter(Boolean).length;
    const scraplingText = options.scrapling_search ? 'Scrapling 已启用' : 'Scrapling 未启用';
    el.textContent = `${enabled}/${Object.keys(options).length} 个模块启用，${scraplingText}`;
  },

  async loadCompanies() {
    const body = document.getElementById('company-table-body');
    body.innerHTML = '<tr><td colspan="5">加载中...</td></tr>';
    try {
      const companies = await API.getCompanies();
      this.companies = companies;
      if (!companies.length) {
        body.innerHTML = '<tr><td colspan="5">暂无公司，先发起一次研究。</td></tr>';
        return;
      }
      this.renderCompanies();
    } catch (e) {
      body.innerHTML = `<tr><td colspan="5">公司库加载失败：${this.esc(e.message)}</td></tr>`;
    }
  },

  renderCompanies() {
    const body = document.getElementById('company-table-body');
    body.innerHTML = this.companies.map(company => {
      const rows = [this.renderCompanyRow(company)];
      if (company.company_name === this.expandedCompany) {
        rows.push(this.renderCompanyDetailRow(company.company_name));
      }
      return rows.join('');
    }).join('');
  },

  renderCompanyRow(company) {
    const completeness = Number(company.completeness || 0);
    const level = completeness >= 80 ? 'high' : completeness >= 60 ? 'mid' : 'low';
    const researchedAt = this.formatDate(company.researched_at || company.created_at);
    const name = this.esc(company.company_name);
    const encodedName = encodeURIComponent(company.company_name);
    const encodedUrl = encodeURIComponent(company.company_url || company.website_url || '');
    const confirmed = Number(company.confirmed || 0);
    const total = Number(company.total || CARD_COUNT);
    const expanded = company.company_name === this.expandedCompany;
    return `<tr class="company-row ${expanded ? 'is-expanded' : ''}" data-company="${encodedName}" title="点击展开研究信息">
      <td><span class="row-caret">${expanded ? '▾' : '▸'}</span>${name}</td>
      <td>${researchedAt}</td>
      <td><span class="completeness ${level}">${completeness}%</span></td>
      <td>${confirmed}/${total}</td>
      <td>
        <a class="btn btn-sm" href="/editor?company=${encodedName}">定稿</a>
        <button class="btn btn-sm" data-refill-company="${this.esc(encodedName)}" data-refill-url="${this.esc(encodedUrl)}">重研</button>
      </td>
    </tr>`;
  },

  async toggleCompanyDetails(companyName) {
    if (this.expandedCompany === companyName) {
      this.expandedCompany = '';
      this.renderCompanies();
      return;
    }

    this.expandedCompany = companyName;
    this.renderCompanies();

    if (this.detailsByCompany[companyName]) return;
    try {
      this.detailsByCompany[companyName] = await API.getAllVersions(companyName);
      // 同时加载字段分辨率状态
      this._loadResolutionSummary(companyName);
    } catch (e) {
      this.detailsByCompany[companyName] = { _error: e.message };
    }
    if (this.expandedCompany === companyName) this.renderCompanies();
  },

  async _loadResolutionSummary(companyName) {
    try {
      const r = await fetch(`/api/company/${encodeURIComponent(companyName)}/all-fields`);
      const d = await r.json();
      this._resolutionByCompany = this._resolutionByCompany || {};
      this._resolutionByCompany[companyName] = d.resolution_summary || {};
    } catch (_) {}
  },

  renderCompanyDetailRow(companyName) {
    const details = this.detailsByCompany[companyName];
    const encodedName = encodeURIComponent(companyName);
    let content = '<div class="company-detail-loading">正在读取研究信息...</div>';
    if (details?._error) {
      content = `<div class="company-detail-error">研究信息加载失败：${this.esc(details._error)}</div>`;
    } else if (details) {
      content = this.renderCompanyDetails(details, encodedName);
    }
    return `<tr class="company-detail-row" data-company-detail="${encodedName}">
      <td colspan="5">${content}</td>
    </tr>`;
  },

  renderCompanyDetails(versions, encodedName) {
    const standard = versions.standard || versions.business || versions.spread || {};
    const facts = [
      ['类型', standard.company_type],
      ['地点', standard.location],
      ['创始人', standard.founder_name],
      ['学历背景', standard.founder_edu],
      ['工作背景', standard.founder_bg],
      ['过往成就', standard.founder_achievement],
      ['团队', standard.team_size],
      ['融资', standard.funding_info],
      ['主产品', standard.main_product_name],
      ['置信度', standard.data_confidence],
    ];
    const resolution = (this._resolutionByCompany || {})[companyName] || {};
    const statusLabels = {
      confirmed: '已确认', derived: '公式计算', proxy: '代理估算',
      llm_extracted: 'LLM提取', unavailable: '不可得', manual_needed: '需人工',
      not_applicable: '不适用',
    };
    const statusColors = {
      confirmed: '#22c55e', derived: '#3b82f6', proxy: '#f59e0b',
      llm_extracted: '#8b5cf6', unavailable: '#9ca3af', manual_needed: '#ef4444',
      not_applicable: '#6b7280',
    };
    const resBadges = Object.entries(resolution).length
      ? Object.entries(resolution).map(([k, v]) =>
          `<span style="display:inline-flex;align-items:center;gap:3px;font-size:10px;padding:2px 6px;border-radius:999px;background:${
            statusColors[k] || '#9ca3af'}18;color:${statusColors[k] || '#9ca3af'};white-space:nowrap;">${
            statusLabels[k] || k} ${v}</span>`).join(' ')
      : '<span style="font-size:10px;color:var(--text-muted)">暂无分辨率数据（旧研究需重跑）</span>';

    return `<div class="company-detail-panel">
      <div class="company-detail-top">
        <div>
          <div class="company-detail-title">研究信息</div>
          <div class="company-detail-subtitle">点击其他公司会自动收起当前详情。</div>
        </div>
        <a class="btn btn-sm" href="/editor?company=${encodedName}">进入定稿</a>
      </div>
      <div class="detail-fact-grid">
        ${facts.map(([label, value]) => `<div class="detail-fact"><span>${this.esc(label)}</span><strong>${this.esc(this.compactValue(value))}</strong></div>`).join('')}
      </div>
      <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border,#E2E4E9);display:flex;flex-wrap:wrap;gap:4px;align-items:center;">
        <span style="font-size:10px;color:var(--text-muted);margin-right:4px;">字段状态</span>
        ${resBadges}
      </div>
    </div>`;
  },

  compactValue(value, maxLength = 80) {
    const text = this.stringifyValue(value).replace(/\s+/g, ' ').trim();
    if (!text) return '暂缺';
    return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
  },

  stringifyValue(value) {
    if (value === null || value === undefined || value === '') return '';
    if (Array.isArray(value)) {
      return value.map(item => this.stringifyValue(item)).filter(Boolean).join('；');
    }
    if (typeof value === 'object') {
      return Object.values(value).map(item => this.stringifyValue(item)).filter(Boolean).join(' / ');
    }
    return String(value);
  },

  refillResearch(encodedName, encodedUrl = '') {
    document.getElementById('research-company-name').value = decodeURIComponent(encodedName);
    const urlInput = document.getElementById('research-company-url');
    urlInput.value = decodeURIComponent(encodedUrl);
    urlInput.focus();
  },

  async startResearch() {
    const nameInput = document.getElementById('research-company-name');
    const urlInput = document.getElementById('research-company-url');
    const btn = document.getElementById('btn-start-research');
    const companyName = nameInput.value.trim();
    const companyUrl = urlInput.value.trim();
    if (!companyName || !companyUrl) {
      this.setProgress('failed', '研究失败', '请填写公司名和官网 URL');
      return;
    }
    if (btn.disabled || this.activeJobId) return;
    const researchOptions = this.collectResearchOptions();
    this.saveResearchOptions();

    clearInterval(this.pollTimer);
    this.pollTimer = null;
    this.activeJobId = 'starting';
    this.pollInFlight = false;
    this.currentProgressPercent = 0;
    this.currentSources = {};
    btn.disabled = true;
    document.getElementById('research-complete').classList.add('hidden');
    document.getElementById('research-complete').innerHTML = '';
    this.setProgress('running', '启动', '正在提交研究任务...', {}, []);

    try {
      const job = await API.startResearch(companyName, companyUrl, researchOptions);
      this.activeJobId = job.job_id;
      localStorage.setItem('gzh2_active_job', JSON.stringify({
        jobId: job.job_id,
        companyName,
        researchOptions,
        ts: Date.now(),
      }));
      document.getElementById('btn-stop-research').style.display = '';
      this.pollJob(job.job_id, companyName, btn);
    } catch (e) {
      this.activeJobId = null;
      btn.disabled = false;
      localStorage.removeItem('gzh2_active_job');
      document.getElementById('btn-stop-research').style.display = 'none';
      this.setProgress('failed', '研究失败', e.message);
    }
  },

  pollJob(jobId, companyName, btn) {
    clearInterval(this.pollTimer);
    const poll = async () => {
      if (this.activeJobId !== jobId || this.pollInFlight) return;
      this.pollInFlight = true;
      try {
        const job = await API.getResearchStatus(jobId);
        if (job.status === 'done') {
          clearInterval(this.pollTimer);
          this.pollTimer = null;
          this.activeJobId = null;
          btn.disabled = false;
          localStorage.removeItem('gzh2_active_job');
          document.getElementById('btn-stop-research').style.display = 'none';
          this.setProgress('done', '研究完成', job.detail || '已写入数据库', job.sources || {}, job.stages || []);
          document.getElementById('research-complete').classList.remove('hidden');
          document.getElementById('research-complete').innerHTML =
            `<a class="btn btn-primary" href="/editor?company=${encodeURIComponent(companyName)}">研究完成 · 进入定稿 →</a>`;
          await this.loadCompanies();
        } else if (job.status === 'failed' || job.status === 'cancelled') {
          clearInterval(this.pollTimer);
          this.pollTimer = null;
          this.activeJobId = null;
          btn.disabled = false;
          localStorage.removeItem('gzh2_active_job');
          document.getElementById('btn-stop-research').style.display = 'none';
          if (job.status === 'cancelled') {
            this.setProgress('cancelled', '已停止', job.detail || '研究已停止', job.sources || {}, job.stages || []);
          } else {
            this.setProgress('failed', '研究失败', job.error || job.detail || '未知错误', job.sources || {}, job.stages || []);
          }
        } else {
          this.setProgress(job.status, job.stage || 'running', job.detail || '', job.sources || {}, job.stages || []);
        }
      } catch (e) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
        this.activeJobId = null;
        btn.disabled = false;
        localStorage.removeItem('gzh2_active_job');
        document.getElementById('btn-stop-research').style.display = 'none';
        this.setProgress('failed', '研究失败', e.message, {}, []);
      } finally {
        this.pollInFlight = false;
      }
    };
    poll();
    this.pollTimer = setInterval(poll, 2000);
  },

  async stopResearch() {
    if (!this.activeJobId || this.activeJobId === 'starting') return;
    const jobId = this.activeJobId;
    this.clearActiveResearchRun();
    try {
      const response = await fetch(`/api/research/stop/${encodeURIComponent(jobId)}`, { method: 'POST' });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || `停止失败：HTTP ${response.status}`);
      }
    } catch (e) {
      console.error('停止失败:', e);
    }
  },

  clearActiveResearchRun() {
    clearInterval(this.pollTimer);
    this.pollTimer = null;
    this.activeJobId = null;
    this.pollInFlight = false;
    this.currentProgressPercent = 0;
    this.currentSources = {};
    localStorage.removeItem('gzh2_active_job');

    const startBtn = document.getElementById('btn-start-research');
    if (startBtn) startBtn.disabled = false;
    const stopBtn = document.getElementById('btn-stop-research');
    if (stopBtn) stopBtn.style.display = 'none';

    const complete = document.getElementById('research-complete');
    if (complete) {
      complete.classList.add('hidden');
      complete.innerHTML = '';
    }

    const progress = document.getElementById('research-progress');
    if (progress) {
      progress.classList.add('hidden');
      progress.dataset.status = 'idle';
    }
    document.getElementById('research-stage').textContent = '待命';
    document.getElementById('research-percent').textContent = '0%';
    document.getElementById('research-progress-fill').style.width = '0%';
    document.getElementById('research-detail').textContent = '';
    document.getElementById('research-step-track').innerHTML = '';
    document.getElementById('research-event-list').innerHTML = '';
    document.getElementById('source-status-grid').innerHTML = '';
  },

  async _restoreActiveJob() {
    let saved = null;
    try {
      saved = JSON.parse(localStorage.getItem('gzh2_active_job') || 'null');
    } catch {
      saved = null;
    }

    if (saved && Date.now() - Number(saved.ts || 0) > 7200000) {
      localStorage.removeItem('gzh2_active_job');
      saved = null;
    }

    let runningJob = null;
    if (saved?.jobId) {
      try {
        const r = await fetch(`/api/research/status/${encodeURIComponent(saved.jobId)}`);
        const j = await r.json();
        if (j.status === 'running' || j.status === 'cancelling') {
          runningJob = j;
        } else {
          localStorage.removeItem('gzh2_active_job');
          saved = null;
        }
      } catch {
        runningJob = null;
      }
    }

    if (!runningJob) {
      try {
        const r = await fetch('/api/research/running');
        const j = await r.json();
        if (j.status && j.status !== 'none') runningJob = j;
      } catch {
        runningJob = null;
      }
    }

    if (!runningJob) return;

    const btn = document.getElementById('btn-start-research');
    btn.disabled = true;
    this.activeJobId = runningJob.job_id;
    localStorage.setItem('gzh2_active_job', JSON.stringify({
      jobId: runningJob.job_id,
      companyName: runningJob.company_name || saved?.companyName || '',
      ts: Date.now(),
    }));
    this.setProgress(
      runningJob.status,
      runningJob.stage || '恢复中',
      runningJob.detail || '已检测到进行中的研究，正在恢复...',
      runningJob.sources || {},
      runningJob.stages || []
    );
    document.getElementById('btn-stop-research').style.display = '';
    this.pollJob(runningJob.job_id, runningJob.company_name || saved?.companyName || '', btn);
  },

  setProgress(status, stage, detail, sources, stages = []) {
    const progress = document.getElementById('research-progress');
    progress.classList.remove('hidden');
    const percent = this.stagePercent(stage, status);
    document.getElementById('research-stage').textContent = stage;
    document.getElementById('research-percent').textContent = `${percent}%`;
    document.getElementById('research-progress-fill').style.width = `${percent}%`;
    document.getElementById('research-detail').textContent = this.detailText(detail);
    this.renderProgressSteps(stage, status);
    this.renderProgressEvents(stages, stage, detail);
    if (sources !== undefined) this.currentSources = sources || {};
    this.renderSourceStatus(this.currentSources);
    progress.dataset.status = status;
  },

  detailText(detail) {
    if (!detail) return '';
    if (typeof detail === 'object') return detail.message || '';
    return String(detail);
  },

  renderSourceStatus(sources) {
    const grid = document.getElementById('source-status-grid');
    grid.innerHTML = SOURCE_ORDER.map((key) => {
      const source = sources[key] || {};
      const status = source.status || 'pending';
      const label = source.label || SOURCE_LABELS[key] || key;
      const count = Number(source.count || 0);
      const unit = source.unit || '条';
      const detail = source.detail || '等待采集';
      return `<div class="source-card source-${status}">
        <div class="source-card-head">
          <span class="source-name">${this.esc(label)}</span>
          <span class="source-badge">${this.sourceStatusLabel(status)}</span>
        </div>
        <div class="source-metric">${count}<span>${this.esc(unit)}</span></div>
        <div class="source-detail">${this.esc(detail)}</div>
      </div>`;
    }).join('');
  },

  sourceStatusLabel(status) {
    return {
      ok: '有效',
      empty: '空',
      failed: '失败',
      skipped: '跳过',
      pending: '等待',
      collecting: '采集中',
      warning: '不足',
      not_configured: '未配置',
      disabled: '未启用',
      not_applicable: '不适用',
    }[status] || status;
  },

  progressStepIndex(stage) {
    const text = String(stage || '');
    if (text.includes('图片') || text.includes('写库') || text.includes('写入') || text.includes('候选图')) {
      return RESEARCH_PROGRESS_STEPS.findIndex(step => step.id === 'persist');
    }
    const index = RESEARCH_PROGRESS_STEPS.findIndex(step =>
      step.matches.some(keyword => text.includes(keyword))
    );
    return index >= 0 ? index : 0;
  },

  stagePercent(stage, status) {
    if (status === 'done') return 100;
    const step = RESEARCH_PROGRESS_STEPS[this.progressStepIndex(stage)];
    const nextPercent = step?.percent || 5;
    if (status === 'failed' || status === 'cancelled') {
      return Math.max(this.currentProgressPercent || 0, nextPercent);
    }
    this.currentProgressPercent = Math.max(this.currentProgressPercent || 0, nextPercent);
    return this.currentProgressPercent;
  },

  renderProgressSteps(stage, status) {
    const track = document.getElementById('research-step-track');
    if (!track) return;
    const activeIndex = status === 'done'
      ? RESEARCH_PROGRESS_STEPS.length - 1
      : this.progressStepIndex(stage);
    track.innerHTML = RESEARCH_PROGRESS_STEPS.map((step, index) => {
      let state = 'pending';
      if (status === 'done' || index < activeIndex) state = 'done';
      if (index === activeIndex && status !== 'done') state = 'active';
      if ((status === 'failed' || status === 'cancelled') && index === activeIndex) state = 'failed';
      return `<div class="research-step research-step-${state}">
        <span class="research-step-dot"></span>
        <span class="research-step-label">${this.esc(step.label)}</span>
      </div>`;
    }).join('');
  },

  renderProgressEvents(stages, stage, detail) {
    const list = document.getElementById('research-event-list');
    if (!list) return;
    const events = Array.isArray(stages) ? stages.slice() : [];
    const latestDetail = this.detailText(detail);
    const latest = { stage: stage || '当前进度', detail: latestDetail };
    const tail = events[events.length - 1];
    if (!tail) {
      events.push(latest);
    } else if (tail.stage !== latest.stage) {
      events.push(latest);
    } else {
      events[events.length - 1] = latest;
    }
    const visible = events
      .filter(item => item && (item.stage || item.detail))
      .slice(-6)
      .reverse();
    list.innerHTML = visible.map((item) => {
      const eventStage = item.stage || '进度';
      const eventDetail = this.detailText(item.detail) || '处理中...';
      return `<div class="research-event">
        <span>${this.esc(eventStage)}</span>
        <strong>${this.esc(eventDetail)}</strong>
      </div>`;
    }).join('');
  },

  formatDate(value) {
    if (!value) return '暂缺';
    const date = new Date(String(value).replace(' ', 'T'));
    if (Number.isNaN(date.getTime())) return value;
    const month = `${date.getMonth() + 1}`.padStart(2, '0');
    const day = `${date.getDate()}`.padStart(2, '0');
    const hour = `${date.getHours()}`.padStart(2, '0');
    const minute = `${date.getMinutes()}`.padStart(2, '0');
    return `${month}月${day}日 ${hour}:${minute}`;
  },

  esc(value) {
    return String(value || '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;',
    }[ch]));
  },
};

document.addEventListener('DOMContentLoaded', () => ResearchDesk.init());
