Page({
  data: {
    connected: false, busy: false, base: '', token: '', notice: '',
    ingredients: [], recommendations: [], state: { selected: [], people: 2, minutes: 30 }, recipe: null,
    peopleInput: '2', minutesInput: '30', question: '', answer: '', job: '', generatedRecipe: null,
  },
  onLoad() {
    this.iconCache = {};
    this.setData({ base: wx.getStorageSync('kitchenBase') || wx.getStorageSync('kitchenAppBase') || 'http://127.0.0.1:8765' });
  },
  onShow() {
    if (!this.data.connected) return;
    this.refreshState();
    if (this.data.job) this.poll(this.data.job);
  },
  onHide() { clearTimeout(this.timer); },
  onUnload() { clearTimeout(this.timer); },
  onPullDownRefresh() {
    if (!this.data.connected) return wx.stopPullDownRefresh();
    this.refreshState().finally(() => wx.stopPullDownRefresh());
  },
  input(e) { this.setData({ [e.currentTarget.dataset.field]: e.detail.value }); },
  api(path, data, method) {
    return new Promise((resolve, reject) => wx.request({
      url: this.data.base.replace(/\/$/, '') + '/app/' + path,
      method: method || (data ? 'POST' : 'GET'), data,
      header: { Authorization: 'Bearer ' + this.appToken, 'Content-Type': 'application/json' },
      success: res => res.statusCode >= 200 && res.statusCode < 300 ? resolve(res.data) : reject(new Error((res.data || {}).error || '请求失败：' + res.statusCode)),
      fail: () => reject(new Error('连接失败，请检查服务地址、网络和小程序合法域名。')),
    }));
  },
  async run(work) {
    if (this.data.busy) return;
    this.setData({ busy: true, notice: '' });
    try { await work(); } catch (error) { this.setData({ notice: error.message || '操作失败' }); }
    finally { this.setData({ busy: false }); }
  },
  async refreshState() {
    try { this.apply(await this.api('state')); }
    catch (error) { this.setData({ notice: error.message || '刷新失败' }); }
  },
  connect() {
    this.run(async () => {
      if (!/^https?:\/\/[^\s]+$/.test(this.data.base) || this.data.token.length < 24) throw new Error('请填写后端地址和至少 24 位的小程序口令。');
      this.appToken = this.data.token;
      this.apply(await this.api('state'));
      wx.setStorageSync('kitchenBase', this.data.base);
      this.setData({ connected: true, token: '' });
    });
  },
  disconnect() {
    clearTimeout(this.timer);
    this.appToken = '';
    this.iconCache = {};
    this.setData({ connected: false, token: '', ingredients: [], recommendations: [], recipe: null, answer: '', job: '', generatedRecipe: null });
  },
  apply(snapshot) {
    const selected = snapshot.state.selected || [];
    const ingredients = snapshot.ingredients.map(name => ({ name, selected: selected.includes(name), icon: this.iconCache[name] || '', initial: name.slice(0, 1) }));
    const recommendations = snapshot.recommendations.map(recipe => ({ ...recipe, ingredientText: recipe.ingredients.join('、') }));
    this.setData({ ingredients, recommendations, state: snapshot.state, recipe: snapshot.recipe,
      peopleInput: String(snapshot.state.people), minutesInput: String(snapshot.state.minutes) });
    this.loadIcons(ingredients);
  },
  loadIcons(items) {
    items.forEach((item, i) => {
      if (item.icon) return;
      wx.downloadFile({
        url: this.data.base.replace(/\/$/, '') + '/app/icon?name=' + encodeURIComponent(item.name),
        header: { Authorization: 'Bearer ' + this.appToken },
        success: res => {
          if (res.statusCode !== 200) return;
          this.iconCache[item.name] = res.tempFilePath;
          if (this.data.ingredients[i] && this.data.ingredients[i].name === item.name) this.setData({ ['ingredients[' + i + '].icon']: res.tempFilePath });
        },
      });
    });
  },
  toggle(e) { this.run(async () => this.apply(await this.api('toggle', { name: e.currentTarget.dataset.name }))); },
  preferences() {
    this.run(async () => {
      const people = Number(this.data.peopleInput), minutes = Number(this.data.minutesInput);
      if (!Number.isInteger(people) || !Number.isInteger(minutes)) throw new Error('人数和时间请填写整数。');
      this.apply(await this.api('preferences', { people, minutes }));
    });
  },
  start(e) { this.run(async () => this.apply(await this.api('start', { recipe: e.currentTarget.dataset.id }))); },
  step(e) { this.run(async () => this.apply(await this.api('step', { delta: Number(e.currentTarget.dataset.delta) }))); },
  ask() { this.run(async () => { const result = await this.api('ask', { question: this.data.question }); this.setData({ job: result.job, answer: '正在向厨房助手询问…' }); this.poll(result.job); }); },
  async poll(id) {
    clearTimeout(this.timer);
    try {
      const result = await this.api('job?id=' + encodeURIComponent(id));
      if (this.data.job !== id || !this.data.connected) return;
      if (result.status === 'done' && result.result.recipe) {
        const recipe = { ...result.result.recipe, ingredientText: result.result.recipe.ingredients.join('、') };
        this.setData({ job: '', generatedRecipe: recipe });
      }
      else if (result.status === 'done') this.setData({ job: '', answer: result.result.answer || '没有收到回答。' });
      else if (result.status === 'failed') this.setData({ job: '', answer: result.error || '提问失败。' });
      else this.timer = setTimeout(() => this.poll(id), 1800);
    } catch (error) { this.setData({ notice: error.message + '；可稍后重试。' }); }
  },
  generateRecipe() { this.run(async () => { const result = await this.api('generate-recipe', {}); this.setData({ job: result.job, generatedRecipe: null, answer: '' }); this.poll(result.job); }); },
  saveGenerated() { this.run(async () => { this.apply(await this.api('save-generated', { recipe: this.data.generatedRecipe })); this.setData({ generatedRecipe: null, notice: 'AI 菜谱已保存到菜谱库。' }); }); },
  manage() { wx.navigateTo({ url: '/pages/manage/index' }); },
});
