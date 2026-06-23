/* workspace-image.js — 抓取图工作区 */
const WorkspaceImage = {
  async mount({ company, slot, editorArea, candidatePanel, onRefresh, onToast, loadCardMarkdown }) {
    if (!editorArea || !candidatePanel || !slot) return;
    document.body.classList.remove('chart-mode');
    editorArea.classList.remove('chart-editor-area');
    editorArea.classList.add('image-editor-area');
    candidatePanel.classList.remove('param-panel');
    candidatePanel.classList.add('candidate-panel');

    SearchPanel.init(editorArea, {
      onFetch: async (imageData) => {
        const result = await StudioAPI.fetch(company, slot.asset_key, imageData);
        VariantSidebar.showCopyrightModal(imageData);
        await VariantSidebar.refresh();
        if (result && result.id) {
          const v = VariantSidebar._variants.find(v => v.id === result.id);
          if (v) VariantSidebar._previewVariant(v.id);
        }
      },
      onRefresh: async () => {
        await VariantSidebar.refresh();
        if (onRefresh) onRefresh();
      },
    });
    VariantSidebar._rendered = false;
    VariantSidebar.init(candidatePanel, {
      onSelect: () => onRefresh && onRefresh(),
      onPreview: (src) => SearchPanel.showPreviewImage(src || ''),
    });

    SearchPanel.setContext(company, slot.asset_key);
    VariantSidebar.setContext(company, slot.asset_key);
    SearchPanel.showAll();
    SearchPanel.setSlotImage(slot.local_path || '', slot.status || '');

    let queries = QueryGen.get(company, slot.asset_key);
    if (!queries && loadCardMarkdown && slot.card_index) {
      const markdown = await loadCardMarkdown(slot.card_index);
      if (markdown) queries = await QueryGen.fetch(company, slot.asset_key, markdown);
    }
    SearchPanel.setQueries(queries || QueryGen.fallback(slot.asset_key));
    if (onToast) onToast(`${this._label(slot.asset_key)} 已载入`, 'info');
  },

  _label(assetKey) {
    return (window.DEMAND_LABELS && window.DEMAND_LABELS[assetKey]) || assetKey;
  },
};
