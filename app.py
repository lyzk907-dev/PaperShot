"""Windows desktop UI for PaperShot. No pip packages required."""
from __future__ import annotations

import copy
import os
import queue
import socket
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

import core

ROOT = Path(__file__).resolve().parent


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('PaperShot')
        if (ROOT / 'PaperShot.ico').exists():
            self.iconbitmap(str(ROOT / 'PaperShot.ico'))
        self.geometry('1120x820')
        self.minsize(900, 650)
        self.configure(bg='#f3f6fa')
        self.store = core.Store(ROOT / 'data')
        self.events = queue.Queue()
        self.busy = False
        self.current = None
        self.network_retry = core.NetworkRetry()
        self.network_checking = False
        self.network_day = core.now().date().isoformat()
        self.vars = {}
        self.texts = {}
        self.actions = []
        try:
            self.config_data = self.store.load()
        except Exception:
            self.config_data = dict(core.DEFAULTS)
            messagebox.showerror('配置读取失败', '配置文件损坏或 Windows 凭据无法解密。已使用空白配置，请重新填写设置；历史日报仍可查看。')
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('TButton', padding=(12, 7))
        style.configure('TNotebook.Tab', padding=(20, 10))
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 23, 'bold'))
        header = ttk.Frame(self, padding=(22, 16))
        header.pack(fill='x')
        ttk.Label(header, text='PaperShot', style='Title.TLabel').pack(anchor='w')
        ttk.Label(header, text='每日衔来新知 · 为你的兴趣而读', foreground='#53627a').pack(anchor='w', pady=(5, 0))
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='both', expand=True, padx=18, pady=(0, 10))
        self.today_tab = ttk.Frame(self.tabs, padding=14)
        self.settings_tab = ttk.Frame(self.tabs)
        self.history_tab = ttk.Frame(self.tabs, padding=14)
        self.tabs.add(self.today_tab, text='阅读与推送')
        self.tabs.add(self.settings_tab, text='兴趣与设置')
        self.tabs.add(self.history_tab, text='历史日报')
        self.build_today()
        self.build_settings()
        self.build_history()
        self.status = tk.StringVar(value='就绪。首次使用请在“兴趣与设置”中填写 API、关键词和邮箱。')
        ttk.Label(self, textvariable=self.status, padding=(20, 8), wraplength=1040).pack(fill='x')
        self.refresh_history()
        records = self.store.history()
        if records:
            self.show_digest(records[0][0])
        else:
            self.tabs.select(self.settings_tab)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(150, self.poll)
        self.after(2000, self.schedule)

    def button(self, parent, label, command):
        b = ttk.Button(parent, text=label, command=command)
        b.pack(side='left', padx=(0, 7), pady=4)
        self.actions.append(b)
        return b

    def build_today(self):
        row = ttk.Frame(self.today_tab)
        row.pack(fill='x')
        self.button(row, '生成一组论文', self.generate)
        self.button(row, '再来 10 篇', lambda: self.generate(extra=True))
        self.button(row, '发送当前这期到邮箱', self.send_current)
        self.button(row, '导出 Markdown', self.export)
        self.button(row, '运行今日定时任务', self.daily)
        ttk.Label(self.today_tab, text='手动生成仅保存到本地，点击发送才投递邮件。每日任务会自动生成并发送。', foreground='#53627a').pack(anchor='w', pady=(8, 10))
        self.reader = scrolledtext.ScrolledText(self.today_tab, wrap='word', font=('Microsoft YaHei UI', 11), padx=18, pady=16, relief='flat', background='#ffffff', spacing3=8)
        self.reader.pack(fill='both', expand=True)
        self.reader.insert('1.0', '在设置中填写研究关键词和模型 API，然后生成你的第一组论文。\n\n默认结构：背景、动机、方法创新（输入/输出）、实验设计（数据集/基线/指标）、主要结果、局限与阅读建议。')
        self.reader.configure(state='disabled')
        self.logbox = scrolledtext.ScrolledText(self.today_tab, height=4, wrap='word', font=('Microsoft YaHei UI', 9), background='#edf2f7', relief='flat')
        self.logbox.pack(fill='x', pady=(10, 0))
        self.logbox.configure(state='disabled')

    def build_settings(self):
        outer = ttk.Frame(self.settings_tab)
        outer.pack(fill='both', expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0, bg='#f3f6fa')
        bar = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        self.form = ttk.Frame(canvas, padding=20)
        window = canvas.create_window((0, 0), window=self.form, anchor='nw')
        self.form.columnconfigure(1, weight=1)
        self.form.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        def wheel(event):
            if self.tabs.select() == str(self.settings_tab):
                canvas.yview_scroll(int(-event.delta / 120), 'units')
        self.bind_all('<MouseWheel>', wheel, add='+')
        self.row = 0
        self.section('01 / 模型 API')
        self.hint('支持 Chat Completions 兼容 API。填写服务商的完整基础地址（通常含 /v1）；会向该服务发送研究兴趣及论文文本。')
        self.field('base_url', 'API 基础地址', hint='例如 https://服务商地址/v1；也可填完整 /chat/completions 地址')
        self.field('api_key', 'API Key', secret=True)
        self.field('model', '模型名称', hint='填写服务商提供的模型 ID；建议支持至少 32K 上下文、中文总结和 JSON 输出')
        self.test_row([('测试 API', self.test_api)])
        self.section('02 / 研究兴趣')
        self.field('keywords', '研究关键词', multiline=3, hint='逗号或换行分隔，任一关键词匹配即可。建议使用英文短语，例如 retrieval augmented generation, agent memory')
        self.field('preferences', '偏好描述', multiline=3, hint='例如：偏重可复现的方法研究；关注小样本场景；优先有开源代码的论文。用于模型排序。')
        self.field('exclude', '排除关键词', multiline=2, hint='逗号或换行分隔；标题/摘要命中会直接排除，也会提交给模型参考')
        self.field('categories', 'arXiv 分类（可选）', hint='例如 cs.AI, cs.CL。留空搜索所有分类。关键词和分类同时生效。')
        self.field('count', '每次数量', hint='默认 10，范围 1–30；符合条件不足时只提供实际数量')
        self.field('days', '检索最近多少天', hint='默认 14 天，优先按相关度选取，分数相同时优先较新论文')
        self.field('candidate_limit', '候选论文上限', hint='默认 100，范围 10–300；限取最近的候选，扩大数量会增加 API 用量')
        self.field('min_score', '最低相关分', hint='默认 6，范围 0–10；由模型按兴趣评分，不代表论文质量')
        self.check('full_text', '优先读取 arXiv HTML 正文；失败后使用摘要（不解析 PDF）')
        self.field('extra_prompt', '总结的额外要求', multiline=3, hint='默认已包含背景、动机、方法输入输出、创新、数据集、实验方案、结果及局限；可补充长度和侧重点')
        self.section('03 / 邮箱')
        self.hint('使用邮箱的 SMTP 服务；多数邮箱需要在邮箱设置中开启 SMTP 并生成授权码。只需生成本地日报时可留空。')
        self.field('smtp_host', 'SMTP 服务器', hint='填写邮箱服务商提供的服务器地址，不加 https://')
        self.field('smtp_port', 'SMTP 端口', hint='SSL 通常为 465；STARTTLS 通常为 587，以服务商说明为准')
        self.field('smtp_security', '连接加密', options=('SSL', 'STARTTLS'))
        self.field('smtp_user', 'SMTP 登录账号')
        self.field('smtp_password', '授权码 / 密码', secret=True)
        self.field('sender', '发件邮箱')
        self.field('recipient', '收件邮箱')
        self.test_row([('发送测试邮件', self.test_email)])
        self.section('04 / 每日定时')
        self.check('schedule_enabled', '启用每日自动生成并发邮件（保存设置后生效）')
        self.field('schedule_mode', '自动发送方式', options=('当天首次联网即发送', '到达指定时间后发送'), hint='首次联网模式：当天尚未发送时，检测到服务可连接就立即开始生成或补发，无需等到指定时间。')
        self.field('schedule_time', '每天几点（北京时间）', hint='HH:MM，默认 08:00。仅“到达指定时间后发送”模式使用；错过时间后联网会补发。')
        self.hint('程序须保持运行，可最小化。约每 10 秒检测一次所需服务；断网恢复后立即尝试，不受一小时重试间隔限制。当天已发送则不重复。尚未生成时需先生成总结，生成好的日报直接补发。')
        self.hint('API Key 与邮箱授权码使用 Windows DPAPI 加密保存；只有当前 Windows 账户可解密。兴趣配置、邮件地址及阅读历史保存在程序旁的 data 文件夹。')
        footer = ttk.Frame(self.settings_tab, padding=10)
        footer.pack(fill='x')
        self.button(footer, '保存所有设置', self.save)
        ttk.Label(footer, text='设置可随时修改；不需要编辑代码。').pack(side='left', padx=10)

    def section(self, text):
        ttk.Label(self.form, text=text, font=('Microsoft YaHei UI', 14, 'bold')).grid(row=self.row, column=0, columnspan=2, sticky='w', pady=(18, 12))
        self.row += 1

    def hint(self, text):
        ttk.Label(self.form, text=text, foreground='#53627a', wraplength=800).grid(row=self.row, column=0, columnspan=2, sticky='w', pady=(0, 12))
        self.row += 1

    def field(self, key, label, multiline=0, secret=False, options=None, hint=''):
        ttk.Label(self.form, text=label).grid(row=self.row, column=0, sticky='nw', padx=(0, 20), pady=7)
        value = self.config_data[key]
        if multiline:
            widget = tk.Text(self.form, height=multiline, wrap='word', font=('Microsoft YaHei UI', 10), relief='solid', borderwidth=1, padx=6, pady=6)
            widget.insert('1.0', str(value))
            self.texts[key] = widget
        else:
            var = tk.StringVar(value=str(value))
            self.vars[key] = var
            if options:
                widget = ttk.Combobox(self.form, textvariable=var, values=options, state='readonly')
            else:
                widget = ttk.Entry(self.form, textvariable=var, show='●' if secret else '')
        widget.grid(row=self.row, column=1, sticky='ew', pady=5)
        self.row += 1
        if hint:
            ttk.Label(self.form, text=hint, foreground='#64748b', wraplength=700).grid(row=self.row, column=1, sticky='w', pady=(0, 7))
            self.row += 1

    def check(self, key, label):
        var = tk.BooleanVar(value=self.config_data[key])
        self.vars[key] = var
        ttk.Checkbutton(self.form, text=label, variable=var).grid(row=self.row, column=0, columnspan=2, sticky='w', pady=8)
        self.row += 1

    def test_row(self, buttons):
        row = ttk.Frame(self.form)
        row.grid(row=self.row, column=1, sticky='w', pady=6)
        for label, action in buttons:
            self.button(row, label, action)
        self.row += 1

    def build_history(self):
        ttk.Label(self.history_tab, text='双击一条记录即可阅读、导出或重新发送。生成成功的论文会自动去重。').pack(anchor='w', pady=(0, 12))
        self.history = ttk.Treeview(self.history_tab, columns=('id', 'date', 'kind', 'sent'), show='headings')
        for key, title, width in [('id', '期数', 70), ('date', '生成时间（北京时间）', 280), ('kind', '来源', 140), ('sent', '发送状态', 160)]:
            self.history.heading(key, text=title)
            self.history.column(key, width=width)
        self.history.pack(fill='both', expand=True)
        self.history.bind('<Double-1>', self.open_history)

    def collect(self):
        data = copy.deepcopy(self.config_data)
        for key, var in self.vars.items():
            value = var.get()
            data[key] = value.strip() if isinstance(value, str) else value
        for key, widget in self.texts.items():
            data[key] = widget.get('1.0', 'end-1c').strip()
        try:
            for key in ('count', 'days', 'candidate_limit', 'min_score', 'smtp_port'):
                data[key] = int(data[key])
        except ValueError:
            raise core.DigestError('数量、天数、候选上限、相关分和端口必须填写整数。') from None
        return data

    def save(self, quiet=False):
        try:
            data = self.collect()
            # Incomplete profiles can be saved before first use.
            if data['schedule_enabled']:
                core.validate(data, email=True)
            self.store.save(data)
            self.config_data = data
            self.network_retry = core.NetworkRetry()
            self.status.set('设置已保存。' + ('每日定时已启用，请保持程序运行。' if data['schedule_enabled'] else '每日定时未启用。'))
            if not quiet:
                messagebox.showinfo('设置已保存', '设置已保存在本机。API Key 与邮箱授权码已加密。')
            return data
        except Exception as exc:
            self.error(exc)
            return None

    def error(self, exc):
        # Never display raw service responses or credential-bearing exceptions.
        text = str(exc) if isinstance(exc, core.DigestError) else '操作失败，请检查配置、文件写入权限或网络后重试。'
        self.status.set(text)
        messagebox.showerror('未完成', text)

    def start(self, work, success, failure=None):
        if self.busy:
            return
        self.busy = True
        for b in self.actions:
            b.configure(state='disabled')
        def runner():
            try:
                self.events.put(('done', (success, work())))
            except Exception as exc:
                self.events.put(('error', (failure, exc)))
        threading.Thread(target=runner, daemon=True).start()

    def log(self, text):
        self.events.put(('log', text))

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'network':
                    self.network_checking = False
                    self.network_result(*value)
                elif kind == 'log':
                    self.status.set(value)
                    self.logbox.configure(state='normal')
                    self.logbox.insert('end', core.now().strftime('%H:%M:%S') + ' ' + value + '\n')
                    self.logbox.see('end')
                    self.logbox.configure(state='disabled')
                else:
                    self.busy = False
                    for b in self.actions:
                        b.configure(state='normal')
                    if kind == 'error':
                        failure, exc = value
                        if failure:
                            failure(exc)
                        else:
                            self.error(exc)
                    else:
                        callback, result = value
                        callback(result)
                    self.refresh_history()
        except queue.Empty:
            pass
        self.after(150, self.poll)

    def generate(self, extra=False):
        data = self.save(quiet=True)
        if data is None:
            return
        if extra:
            data = copy.deepcopy(data)
            data['count'] = 10
        self.tabs.select(self.today_tab)
        self.status.set('准备生成论文总结…')
        self.start(lambda: core.generate(data, self.store, self.log), self.show_digest)

    def daily(self):
        data = self.save(quiet=True)
        if data is not None:
            self.run_daily(data)

    def run_daily(self, data, automatic=False):
        self.network_retry.attempted(time.monotonic())
        self.status.set('正在运行每日任务…')
        self.start(lambda: core.run_daily(copy.deepcopy(data), self.store, self.log), self.show_digest,
                   self.auto_failure if automatic else None)

    def auto_failure(self, exc):
        text = str(exc) if isinstance(exc, core.DigestError) else '自动推送失败，请检查配置或网络。'
        self.log(text + ' 网络恢复后会立即重试；服务持续可连接时每小时重试。')

    def schedule(self):
        config = self.config_data
        day = core.now().date().isoformat()
        if day != self.network_day:
            self.network_day = day
            self.network_retry = core.NetworkRetry()
        if config['schedule_enabled'] and not self.busy and not self.network_checking:
            clock = core.now()
            record = self.store.daily(clock.date().isoformat())
            if core.daily_due(config, record, clock):
                snapshot = copy.deepcopy(config)
                self.network_checking = True
                def probe():
                    try:
                        ready = core.services_reachable(snapshot, has_digest=bool(record))
                    except Exception:
                        ready = False
                    self.events.put(('network', (snapshot, ready)))
                threading.Thread(target=probe, daemon=True).start()
        self.after(10000, self.schedule)

    def network_result(self, snapshot, reachable):
        if snapshot != self.config_data:
            return  # Discard results from before settings were changed.
        clock = core.now()
        record = self.store.daily(clock.date().isoformat())
        if not core.daily_due(snapshot, record, clock):
            return
        should_send = self.network_retry.ready(reachable, time.monotonic())
        if self.busy:
            if should_send:
                self.network_retry.retry_at = 0  # Resume as soon as the current task finishes.
            return
        if should_send:
            self.log('已检测到所需服务可以连接，开始今日推送。')
            self.run_daily(snapshot, automatic=True)
        elif not reachable:
            self.status.set('今日尚未发送，正在等待网络或所需服务恢复（约每 10 秒检测）。')

    def show_digest(self, ident):
        record = self.store.get(ident)
        if not record:
            return
        self.current = ident
        self.reader.configure(state='normal')
        self.reader.delete('1.0', 'end')
        self.reader.insert('1.0', record['content'])
        self.reader.configure(state='disabled')
        self.tabs.select(self.today_tab)
        self.status.set(f'正在阅读第 {ident} 期 · ' + ('已发送到 ' + record['recipient'] if record['sent'] else '已保存在本地，尚未发送'))

    def send_current(self):
        if self.current is None:
            messagebox.showinfo('还没有日报', '请先生成一组论文，或从历史中打开一期。')
            return
        data = self.save(quiet=True)
        if data is None:
            return
        record = self.store.get(self.current)
        if record['sent'] and not messagebox.askyesno('重复发送', f'第 {self.current} 期已经发送过，是否再次发送？'):
            return
        ident = self.current
        self.start(lambda: core.deliver(data, self.store, ident), lambda _: self.show_digest(ident))

    def test_api(self):
        try:
            data = self.collect()
            check = {**data, 'keywords': data['keywords'] or 'test'}
            core.validate(check)
        except Exception as exc:
            self.error(exc)
            return
        self.status.set('正在测试模型 API…')
        self.start(lambda: core.llm(data, 'You are a helpful assistant.', '请只回复：连接成功', 100),
                   lambda _: (self.status.set('API 测试成功。'), messagebox.showinfo('API 测试', '模型 API 连接成功。测试会产生少量模型用量。')))

    def test_email(self):
        try:
            data = self.collect()
            core.validate_email(data)
        except Exception as exc:
            self.error(exc)
            return
        self.status.set('正在发送测试邮件…')
        self.start(lambda: core.send_email(data, '这是一封PaperShot 测试邮件。收到后即可启用每日论文推送。', 'PaperShot · 邮件连接测试'),
                   lambda _: (self.status.set('测试邮件已交给 SMTP 服务器。'), messagebox.showinfo('邮件测试', '测试邮件已发送，请检查收件箱或垃圾邮件。')))

    def export(self):
        if self.current is None:
            return
        path = filedialog.asksaveasfilename(defaultextension='.md', initialfile=f'papershot-{self.current}.md', filetypes=[('Markdown', '*.md')])
        if path:
            try:
                Path(path).write_text(self.store.get(self.current)['content'], encoding='utf-8')
                self.status.set('Markdown 已导出。')
            except OSError:
                messagebox.showerror('导出失败', '无法写入所选位置，请更换文件夹。')

    def refresh_history(self):
        self.history.delete(*self.history.get_children())
        for ident, date, kind, sent in self.store.history():
            self.history.insert('', 'end', iid=str(ident), values=(ident, date.replace('T', ' ')[:19], '每日定时' if kind == 'daily' else '手动生成', '已发送' if sent else '未发送'))

    def open_history(self, event):
        selected = self.history.selection()
        if selected:
            self.show_digest(int(selected[0]))

    def close(self):
        if self.busy:
            messagebox.showinfo('任务进行中', '请等待当前任务完成后再关闭窗口；可先最小化。')
            return
        self.destroy()


def main():
    # One instance per user session, to prevent duplicate schedules and sends.
    import hashlib
    lock = socket.socket()
    port = 40000 + int(hashlib.sha256(str(Path.home()).encode()).hexdigest()[:6], 16) % 20000
    try:
        lock.bind(('127.0.0.1', port))
        lock.listen(1)
    except OSError:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo('PaperShot', '程序已在运行，或启动端口被占用。请查看任务栏中的“PaperShot”。')
        root.destroy()
        return
    try:
        App().mainloop()
    finally:
        lock.close()


if __name__ == '__main__':
    main()
