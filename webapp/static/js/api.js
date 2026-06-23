// API 调用封装（v2 支持 card_set_key）
const API = {
  // ── 套卡 ──
  async getCardSets() {
    const res = await fetch('/api/card-sets');
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async createCardSet(displayName, baseSpec) {
    const res = await fetch('/api/card-sets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: displayName, base_spec: baseSpec }),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async deleteCardSet(setKey) {
    const res = await fetch(`/api/card-sets/${encodeURIComponent(setKey)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async initCompanySet(company, setKey) {
    const res = await fetch(`/api/final/${encodeURIComponent(company)}/init-set/${encodeURIComponent(setKey)}`, { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async deleteCompanySetData(company, setKey) {
    const res = await fetch(`/api/final/${encodeURIComponent(company)}/set/${encodeURIComponent(setKey)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  // ── 公司列表 ──
  async getCompanies() {
    const res = await fetch('/api/companies');
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async getAllVersions(company) {
    const res = await fetch(`/api/research/${encodeURIComponent(company)}`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async getResearch(company, version) {
    const res = await fetch(`/api/research/${encodeURIComponent(company)}/${version}`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async getResearchCard(company, cardIndex, version) {
    const params = new URLSearchParams({ version: version || 'standard' });
    const res = await fetch(`/api/research/${encodeURIComponent(company)}/card/${cardIndex}?${params}`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async startResearch(companyName, companyUrl, researchOptions) {
    const res = await fetch('/api/research/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_name: companyName,
        company_url: companyUrl,
        research_options: researchOptions || {}
      })
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async getResearchStatus(jobId) {
    const res = await fetch(`/api/research/status/${encodeURIComponent(jobId)}`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async saveFinal(companyName, cardIndex, fields, imgPaths, cardSetKey) {
    const res = await fetch('/api/final/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_name: companyName,
        card_index: cardIndex,
        card_set_key: cardSetKey || 'v1',
        fields: fields,
        img_paths: imgPaths || {}
      })
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async saveFinalMarkdown(companyName, cardIndex, markdownContent, cardSetKey) {
    const res = await fetch('/api/final/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_name: companyName,
        card_index: cardIndex,
        card_set_key: cardSetKey || 'v1',
        markdown_content: markdownContent
      })
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async getFinalCard(company, cardIndex, cardSetKey) {
    const params = new URLSearchParams();
    if (cardSetKey) params.set('set', cardSetKey);
    const qs = params.toString();
    const res = await fetch(`/api/final/card/${encodeURIComponent(company)}/${cardIndex}${qs ? '?' + qs : ''}`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async getFinalStatus(company, cardSetKey) {
    const params = new URLSearchParams();
    if (cardSetKey) params.set('set', cardSetKey);
    const qs = params.toString();
    const res = await fetch(`/api/final/status/${encodeURIComponent(company)}${qs ? '?' + qs : ''}`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async exportCompany(company, cardSetKey) {
    const params = new URLSearchParams({ format: 'json' });
    if (cardSetKey) params.set('set', cardSetKey);
    const res = await fetch(`/api/final/export/${encodeURIComponent(company)}?${params}`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async checkStatus(company) {
    const res = await fetch(`/api/check/${encodeURIComponent(company)}`);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async generateImage(companyName, fieldName, prompt) {
    const res = await fetch('/api/generate-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_name: companyName,
        field_name: fieldName,
        prompt: prompt
      })
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },

  async splitText(text, segmentCount) {
    const res = await fetch('/api/split-text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text, segment_count: segmentCount })
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
};
