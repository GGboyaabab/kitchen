(function () {
  'use strict';
  var states = [], state, index = 0, timer = null, ticks = 0;
  var names = {idle:'选食材 →',planning:'正在思考…',ready:'看看菜单 →',cooking:'这一步做好了 →',done:'再做一道 →',error:'重试连接 →'};
  var $ = function (id) { return document.getElementById(id); };
  function stop() {
    clearTimeout(timer); timer = null;
    $('play').textContent = '播放一次';
  }
  function render() {
    var path = 'frames/' + state.id + '-' + index + '.svg';
    $('character').src = path;
    $('character').alt = state.label + '状态的 Hello Kitty，第' + (index + 1) + '帧';
    $('download').href = path;
    $('meta').textContent = (timer ? '正在预览' : '静态预览') + ' · 第 ' + (index + 1) + ' / 4 帧 · 设计间隔 ' + state.interval / 1000 + ' 秒';
    var frames = $('filmstrip').children;
    for (var i = 0; i < frames.length; i++) frames[i].className = 'frame' + (i === index ? ' current' : '');
  }
  function select(item) {
    stop(); state = item; index = 0;
    $('title').textContent = item.title; $('copy').textContent = item.text;
    $('detail').textContent = item.detail; $('action').textContent = names[item.id];
    $('filmstrip').textContent = '';
    for (var i = 0; i < 4; i++) {
      var frame = document.createElement('div'); frame.className = 'frame';
      var img = document.createElement('img'); img.src = 'frames/' + item.id + '-' + i + '.svg'; img.alt = item.label + '第' + (i + 1) + '帧';
      var caption = document.createElement('span'); caption.textContent = 'FRAME 0' + (i + 1);
      frame.appendChild(img); frame.appendChild(caption); $('filmstrip').appendChild(frame);
    }
    var buttons = $('states').children;
    for (var b = 0; b < buttons.length; b++) buttons[b].setAttribute('aria-pressed', states[b].id === item.id ? 'true' : 'false');
    render();
  }
  function tick() {
    ticks++; index = ticks % 4;
    if (ticks >= state.loops * 4) { index = state.id === 'ready' || state.id === 'done' ? 3 : 0; stop(); render(); return; }
    timer = setTimeout(tick, state.interval); render();
  }
  $('play').onclick = function () {
    if (timer) { stop(); render(); return; }
    if ($('static').checked || state.id === 'cooking' || state.id === 'error') { stop(); render(); return; }
    ticks = 0; index = 0; timer = setTimeout(tick, state.interval); $('play').textContent = '暂停'; render();
  };
  $('next').onclick = function () { stop(); index = (index + 1) % 4; render(); };
  $('reset').onclick = function () { stop(); index = 0; render(); };
  $('static').onchange = function () { stop(); render(); };
  $('action').onclick = function () { $('detail').textContent = '这是动画预览；这里的按钮不会启动真实做饭或生成任务。'; };
  document.addEventListener('visibilitychange', function () { if (document.hidden) { stop(); if (state) render(); } });
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) $('static').checked = true;
  var req = new XMLHttpRequest(); req.open('GET', 'states.json');
  req.onload = function () {
    if (req.status !== 200) { $('detail').textContent = '状态文件加载失败，请通过本地服务打开本页。'; return; }
    states = JSON.parse(req.responseText);
    states.forEach(function (item) {
      var button = document.createElement('button'); button.textContent = item.label;
      button.onclick = function () { select(item); }; $('states').appendChild(button);
    });
    select(states[0]);
  };
  req.onerror = function () { $('detail').textContent = '加载失败，请通过 python app.py 的本地地址打开。'; };
  req.send();
}());
