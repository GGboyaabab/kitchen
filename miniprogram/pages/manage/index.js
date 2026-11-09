Page({
  data: {
    connected: false, busy: false, tab: 'ingredients', base: '', token: '', notice: '',
    ingredients: [], recipes: [], models: [], names: '', note: '', photo: '',
    recipeDraft: null, modelDraft: null, job: '',
  },
  onLoad() { this.setData({ base: wx.getStorageSync('kitchenBase') || 'http://127.0.0.1:8765' }); },
  onShow() { if (this.data.connected && this.data.job) this.poll(this.data.job); },
  onHide() { clearTimeout(this.timer); },
  onUnload() { clearTimeout(this.timer); },
  input(e) { this.setData({ [e.currentTarget.dataset.field]: e.detail.value }); },
  recipeInput(e) { this.setData({ ['recipeDraft.' + e.currentTarget.dataset.field]: e.detail.value }); },
  modelInput(e) { this.setData({ ['modelDraft.' + e.currentTarget.dataset.field]: e.detail.value }); },
  tab(e) { this.setData({ tab: e.currentTarget.dataset.tab, notice: '' }); },
  api(path, data, method) {
    return new Promise((resolve, reject) => wx.request({
      url: this.data.base.replace(/\/$/, '') + '/admin/' + path,
      method: method || (data ? 'POST' : 'GET'), data,
      header: { Authorization: 'Bearer ' + this.adminToken, 'Content-Type': 'application/json' },
      success: res => res.statusCode >= 200 && res.statusCode < 300 ? resolve(res.data) : reject(new Error((res.data || {}).error || '请求失败：' + res.statusCode)),
      fail: () => reject(new Error('连接失败，请检查服务地址、网络及小程序合法域名配置。')),
    }));
  },
  async run(work) {
    if (this.data.busy) return;
    this.setData({ busy: true, notice: '' });
    try { await work(); } catch (error) { this.setData({ notice: error.message || '操作失败' }); }
    finally { this.setData({ busy: false }); }
  },
  connect() {
    this.run(async () => {
      if (!/^https?:\/\/[^\s]+$/.test(this.data.base) || this.data.token.length < 24) throw new Error('请填写后端地址和至少 24 位的管理口令。');
      this.adminToken = this.data.token;
      await this.refresh();
      wx.setStorageSync('kitchenBase', this.data.base);
      this.setData({ connected: true, token: '' });
    });
  },
  disconnect() {
    clearTimeout(this.timer);
    this.adminToken = '';
    this.setData({ connected: false, ingredients: [], recipes: [], models: [], recipeDraft: null, modelDraft: null, job: '', notice: '', token: '' });
  },
  async refresh() {
    const [ingredients, recipes, models] = await Promise.all([this.api('ingredients'), this.api('recipes'), this.api('models')]);
    this.setData({ ingredients: ingredients.ingredients.map(item => ({ ...item, initial: item.name.slice(0, 1) })), recipes: recipes.recipes, models: models.models });
    this.loadImages();
  },
  reload() { this.run(() => this.refresh()); },
  loadImages() {
    this.data.ingredients.forEach((ingredient, i) => {
      if (!ingredient.generated) return;
      wx.downloadFile({ url: this.data.base + '/admin/icon?name=' + encodeURIComponent(ingredient.name),
        header: { Authorization: 'Bearer ' + this.adminToken },
        success: res => {
          if (res.statusCode === 200 && this.data.ingredients[i] && this.data.ingredients[i].name === ingredient.name)
            this.setData({ ['ingredients[' + i + '].image']: res.tempFilePath });
        },
      });
    });
  },
  choosePhoto() {
    wx.chooseMedia({ count: 1, mediaType: ['image'], sourceType: ['camera', 'album'], sizeType: ['compressed'],
      success: res => {
        const file = res.tempFiles[0];
        if (file.size > 8 * 1024 * 1024) return this.setData({ notice: '照片超过 8 MB，请压缩后重试。' });
        this.setData({ photo: file.tempFilePath });
      },
    });
  },
  removePhoto() { this.setData({ photo: '' }); },
  recognize() {
    this.run(async () => {
      let result;
      if (this.data.photo) {
        result = await new Promise((resolve, reject) => wx.uploadFile({
          url: this.data.base + '/admin/recognize', filePath: this.data.photo, name: 'photo',
          formData: { note: this.data.note }, header: { Authorization: 'Bearer ' + this.adminToken },
          success: res => {
            try {
              const body = JSON.parse(res.data);
              if (res.statusCode !== 200) throw new Error(body.error || '上传失败');
              resolve(body);
            } catch (error) { reject(error); }
          }, fail: () => reject(new Error('照片上传失败，请检查 uploadFile 合法域名。')),
        }));
      } else result = await this.api('recognize', { note: this.data.note });
      this.startJob(result.job);
    });
  },
  startJob(id) {
    this.setData({ job: id, notice: '任务已提交，正在处理…' });
    this.poll(id);
  },
  async poll(id) {
    clearTimeout(this.timer);
    try {
      const result = await this.api('job?id=' + encodeURIComponent(id));
      if (this.data.job !== id || !this.data.connected) return;
      if (result.status === 'done') {
        this.setData({ job: '', notice: result.result.message || '识别完成，请修改名称后确认加入食材库。' });
        if (result.result.names) this.setData({ names: result.result.names.join('，') });
        await this.refresh();
      } else if (result.status === 'failed') {
        this.setData({ job: '', notice: result.error });
      } else this.timer = setTimeout(() => this.poll(id), 1800);
    } catch (error) { this.setData({ notice: error.message + '；可点击“继续查询”恢复任务。' }); }
  },
  resumeJob() { if (this.data.job) this.poll(this.data.job); },
  addIngredients() {
    this.run(async () => {
      const names = this.data.names.split(/[,，、\n]/).map(s => s.trim()).filter(Boolean);
      await this.api('ingredients/save', { names });
      this.setData({ names: '', photo: '', note: '', notice: '食材已保存，尚未自动生图。' });
      await this.refresh();
    });
  },
  generate(e) {
    const name = e.currentTarget.dataset.name, force = !!e.currentTarget.dataset.force;
    wx.showModal({ title: force ? '重新生成图片' : '生成食材图片', content: '将调用生图 API，可能产生费用。' + (force ? '成功后替换现有图。' : '已有图会直接复用。'),
      success: res => { if (res.confirm) this.run(async () => this.startJob((await this.api('generate', { name, force })).job)); },
    });
  },
  renameIngredient(e) {
    const name = e.currentTarget.dataset.name;
    wx.showModal({ title: '重命名 ' + name, editable: true, placeholderText: '新名称',
      success: res => { if (res.confirm) this.run(async () => { await this.api('ingredients/rename', { name, new_name: res.content }); await this.refresh(); }); },
    });
  },
  deleteIngredient(e) {
    const name = e.currentTarget.dataset.name;
    wx.showModal({ title: '删除食材', content: '删除“' + name + '”？菜谱正在引用的食材需要先从菜谱移除。',
      success: res => { if (res.confirm) this.run(async () => { await this.api('ingredients/delete', { name }); await this.refresh(); }); },
    });
  },
  editRecipe(e) {
    const recipe = this.data.recipes.find(r => r.id === e.currentTarget.dataset.id);
    this.setData({ recipeDraft: recipe ? { ...recipe, ingredientsText: recipe.ingredients.join('，'), amountsText: recipe.amounts.join('\n'), stepsText: recipe.steps.join('\n') } :
      { id: '', name: '', minutes: '20', servings: '2', ingredientsText: '', amountsText: '', stepsText: '' } });
  },
  closeRecipe() { this.setData({ recipeDraft: null }); },
  saveRecipe() {
    this.run(async () => {
      const d = this.data.recipeDraft;
      await this.api('recipes/save', { id: d.id, name: d.name, minutes: Number(d.minutes), servings: Number(d.servings),
        ingredients: d.ingredientsText.split(/[,，、\n]/).map(s => s.trim()).filter(Boolean),
        amounts: d.amountsText.split('\n').map(s => s.trim()).filter(Boolean), steps: d.stepsText.split('\n').map(s => s.trim()).filter(Boolean) });
      this.setData({ recipeDraft: null, notice: '菜谱已保存，首页刷新后可见。' });
      await this.refresh();
    });
  },
  deleteRecipe(e) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({ title: '删除菜谱', content: '确定删除这道菜谱？', success: res => {
      if (res.confirm) this.run(async () => { await this.api('recipes/delete', { id }); await this.refresh(); });
    } });
  },
  editModel(e) {
    const c = this.data.models.find(m => m.role === e.currentTarget.dataset.role);
    this.setData({ modelDraft: { ...c, token: '' } });
  },
  closeModel() { this.setData({ modelDraft: null }); },
  saveModel() {
    this.run(async () => {
      await this.api('models/save', this.data.modelDraft);
      this.setData({ modelDraft: null, notice: '模型配置已保存，Token 不会回传。' });
      await this.refresh();
    });
  },
  clearToken(e) {
    const config = this.data.models.find(m => m.role === e.currentTarget.dataset.role);
    wx.showModal({ title: '移除 Token', content: '仅移除本应用配置，不会在模型厂商处撤销 Key。', success: res => {
      if (res.confirm) this.run(async () => { await this.api('models/save', { ...config, clear_token: true }); await this.refresh(); });
    } });
  },
  testModel(e) {
    this.run(async () => {
      const result = await this.api('models/test', { role: e.currentTarget.dataset.role });
      if (result.job) this.startJob(result.job); else this.setData({ notice: result.message });
    });
  },
});
