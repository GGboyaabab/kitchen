"""Build crisp vector frames; all frames share the same fixed canvas."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
STATES = [
    dict(id='idle', label='待机', title='今天，也好好吃饭。', text='选几样手边的食材，我们一起做顿饭。', detail='待机保持静止；只有唤醒时播放一次眨眼。', interval=2400, loops=1),
    dict(id='planning', label='生成菜谱', title='让我想想，怎么做好吃。', text='正在搭配食材、安排做饭顺序。', detail='Hello Kitty 轻轻歪头，思考气泡缓慢变化；不显示虚构的百分比。', interval=2000, loops=3),
    dict(id='ready', label='菜谱就绪', title='想好了，准备开饭。', text='菜谱已经备好，先看看需要哪些材料。', detail='Hello Kitty 举起小爪打招呼，然后停留。仅在后端成功时进入。', interval=1800, loops=1),
    dict(id='cooking', label='跟做等待', title='慢慢来，这一步不着急。', text='照着步骤做，准备好了再继续。', detail='跟做时保持静态，不用动画分散注意力。', interval=2400, loops=1),
    dict(id='done', label='做饭完成', title='辛苦了，好好享用。', text='这一顿，是你亲手做的。', detail='一颗小星星出现一次，然后停留。', interval=1800, loops=1),
    dict(id='error', label='连接异常', title='稍等，我没连上。', text='当前步骤会保留，连接恢复后再试一次。', detail='静态提示，给出重试入口，不持续闪烁。', interval=2400, loops=1),
]


def frame(state, index):
    closed = state == 'idle' and index == 1
    face = '<path d="M117 126q8 8 16 0m54 0q8 8 16 0"/>' if closed or state == 'cooking' else '<g fill="black" stroke="none"><ellipse cx="125" cy="128" rx="5" ry="7"/><ellipse cx="195" cy="128" rx="5" ry="7"/></g>'
    tilt = [0, -4, 0, 4][index] if state == 'planning' else 0
    arm = '<path fill="white" d="M123 184q-20-8-26 5t17 23"/>'
    if state == 'ready' and index > 0:
        arm = '<path fill="white" d="M121 188q-24 6-30-8l-6-23q-1-12 10-12t13 13l8 13"/>'
    elif state == 'planning':
        arm = '<path fill="white" d="M120 192q-19 5-21-9t11-23q10-3 13 7l5 13"/>'
    accents = ''
    if state == 'planning':
        accents = '<circle cx="252" cy="101" r="3"/><circle cx="267" cy="85" r="5"/><path d="M258 47q-5-16 11-18 7-15 20-4 18-3 17 13 12 16-5 22h-27q-16 1-16-13Z" stroke-width="3"/>'
        for n in range(index + 1):
            accents += '<circle cx="%s" cy="43" r="2" fill="black" stroke="none"/>' % (272 + n * 7)
    elif state == 'idle':
        accents = '<path d="M264 77h12l-12 14h12m5-36h8l-8 10h8" stroke-width="3"/>'
    elif state == 'ready':
        accents = '<path d="m57 119-7-10m5 25H42m25-29-2-11" stroke-width="3"/>' if index > 0 else ''
    elif state == 'done':
        accents = '<path d="m275 73 5 13 14 5-14 5-5 13-5-13-14-5 14-5Z"/>' if index > 0 else ''
    elif state == 'error':
        accents = '<path d="M273 69v17m0 10v1"/>'
    return '''<svg xmlns="http://www.w3.org/2000/svg" width="320" height="280" viewBox="0 0 320 280" role="img" aria-label="Hello Kitty 厨房助手">
<rect width="320" height="280" fill="white"/>
<g stroke="black" stroke-width="4" fill="white" stroke-linecap="round" stroke-linejoin="round">
%s
<path d="M127 175q-20 14-17 54h100q3-40-17-54Z"/>
<path d="M134 180v20h52v-20m-58 20-5 29h74l-5-29Z"/>
<path d="M146 210h28v14h-28Z" stroke-width="3"/>
<ellipse cx="130" cy="237" rx="22" ry="12"/><ellipse cx="190" cy="237" rx="22" ry="12"/>
<path d="M196 182q21-1 25 14t-18 16"/>
%s
<g transform="rotate(%s 160 120)">
<path d="M81 92 83 47q1-10 11-6l34 19q31-8 63 0l33-19q11-4 12 7l3 43q18 17 12 45-5 34-46 41-43 9-88-1-41-9-43-39-3-26 7-45Z"/>
<g fill="none" stroke-width="3.5"><path d="m86 121-25-5m25 17H57m32 12-25 8m170-32 25-5m-25 17h29m-32 12 25 8"/></g>
%s
<ellipse cx="160" cy="144" rx="8" ry="5" stroke-width="3"/>
<g transform="rotate(12 217 69)"><path d="M211 67q-25-25-33-9-9 18 11 25l22-9m11-7q24-26 32-9 8 18-11 25l-21-9Z"/><ellipse cx="217" cy="70" rx="9" ry="11"/></g>
</g>
<path d="M108 258h104" fill="none" stroke-width="2"/>
</g></svg>''' % (accents, arm, tilt, face)


def build():
    target = ROOT / 'frames'
    target.mkdir(exist_ok=True)
    for state in STATES:
        for i in range(4):
            (target / ('%s-%s.svg' % (state['id'], i))).write_text(frame(state['id'], i), encoding='utf-8')
    (ROOT / 'states.json').write_text(json.dumps(STATES, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    build()
