import sys
import os
import re
import time
import threading
import pickle
import requests
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from selenium import webdriver
from selenium.webdriver.common.by import By
from urllib.parse import urljoin

class VideoDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("视频下载器 (HLS/m3u8)")
        self.root.geometry("600x500")
        self.driver = None
        self.cookie_str = ""
        self.cookie_file = "cookies.pkl"  # 本地保存的 Cookie 文件

        # ---------- 界面元素 ----------
        # 视频页面 URL
        ttk.Label(root, text="视频页面地址:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.url_entry = ttk.Entry(root, width=65)
        self.url_entry.grid(row=0, column=1, columnspan=2, padx=5, pady=5)

        # 保存路径
        ttk.Label(root, text="保存到:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.path_var = tk.StringVar(value=os.path.join(os.getcwd(), "downloads"))
        self.path_entry = ttk.Entry(root, textvariable=self.path_var, width=55)
        self.path_entry.grid(row=1, column=1, padx=5, pady=5)
        ttk.Button(root, text="浏览...", command=self.browse_folder).grid(row=1, column=2, padx=5)

        # Cookie 来源选项
        ttk.Label(root, text="Cookie 来源:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.cookie_source = tk.StringVar(value="file")  # file / manual_paste
        ttk.Radiobutton(root, text="使用本地保存的 Cookie（首次需登录一次）",
                        variable=self.cookie_source, value="file").grid(row=2, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(root, text="手动粘贴 Cookie 字符串",
                        variable=self.cookie_source, value="paste").grid(row=3, column=1, columnspan=2, sticky="w")

        # Cookie 文本框（只在粘贴模式需要）
        ttk.Label(root, text="Cookie 字符串:").grid(row=4, column=0, padx=5, pady=5, sticky="w")
        self.cookie_text = tk.Text(root, height=4, width=60)
        self.cookie_text.grid(row=4, column=1, columnspan=2, padx=5, pady=5)

        # 重置 Cookie 按钮（删除本地文件，下次重新登录）
        self.reset_cookie_btn = ttk.Button(root, text="重置本地 Cookie", command=self.reset_cookie)
        self.reset_cookie_btn.grid(row=5, column=0, columnspan=3, pady=5)

        # 进度条与状态
        self.progress = ttk.Progressbar(root, orient="horizontal", length=500, mode="determinate")
        self.progress.grid(row=6, column=0, columnspan=3, padx=5, pady=10)
        self.status_label = ttk.Label(root, text="就绪")
        self.status_label.grid(row=7, column=0, columnspan=3, padx=5)

        # 下载按钮
        self.download_btn = ttk.Button(root, text="开始下载", command=self.start_download)
        self.download_btn.grid(row=8, column=0, columnspan=3, pady=10)

        # 关闭窗口时自动清理驱动
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.path_var.set(folder)

    def update_status(self, msg, progress_val=None):
        self.status_label.config(text=msg)
        if progress_val is not None:
            self.progress["value"] = progress_val
        self.root.update_idletasks()

    def reset_cookie(self):
        """删除本地 Cookie 文件，下次会要求重新登录"""
        if os.path.exists(self.cookie_file):
            os.remove(self.cookie_file)
            messagebox.showinfo("提示", "本地 Cookie 已删除，下一次下载时需要重新登录。")
        else:
            messagebox.showinfo("提示", "没有找到本地 Cookie 文件。")

    def start_download(self):
        """在新线程中启动下载，避免界面卡顿"""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("错误", "请输入视频页面地址")
            return
        self.download_btn.config(state="disabled")
        threading.Thread(target=self._download_thread, args=(url,), daemon=True).start()

    def _download_thread(self, url):
        try:
            self._do_download(url)
        except Exception as e:
            messagebox.showerror("下载失败", str(e))
        finally:
            self.download_btn.config(state="normal")
            self.update_status("就绪", 0)

    def _inject_cookies_from_file(self, driver, url):
        """从本地 pickle 文件加载 Cookie 并注入到当前 session"""
        if not os.path.exists(self.cookie_file):
            return False
        with open(self.cookie_file, "rb") as f:
            cookies = pickle.load(f)
        # 先访问一次目标域，才能添加 Cookie
        driver.get(url)
        try:
            for c in cookies:
                # 有些 Cookie 可能 HttpOnly，Selenium 添加时需要注意
                driver.add_cookie(c)
        except Exception:
            pass
        return True

    def _save_cookies_to_file(self):
        """保存当前浏览器的 Cookie 到本地文件"""
        if self.driver:
            cookies = self.driver.get_cookies()
            with open(self.cookie_file, "wb") as f:
                pickle.dump(cookies, f)

    def _do_download(self, url):
        save_dir = self.path_var.get()
        os.makedirs(save_dir, exist_ok=True)

        self.update_status("正在启动浏览器...", 5)
        options = webdriver.ChromeOptions()
        options.page_load_strategy = 'eager'  # 不等图片广告，加快加载
        self.driver = webdriver.Chrome(options=options)
        self.driver.set_page_load_timeout(20)

        try:
            # ---------------- 登录 / Cookie 处理 ----------------
            source = self.cookie_source.get()

            if source == "paste":
                # 使用粘贴的 Cookie 字符串
                raw_cookie = self.cookie_text.get("1.0", tk.END).strip()
                if not raw_cookie:
                    raise Exception("请粘贴有效的 Cookie 字符串")
                self.cookie_str = raw_cookie
                # 先打开主页，注入 Cookie
                self.driver.get("https://网站主域名/")   # 替换成你要的实际主域名
                for pair in raw_cookie.split("; "):
                    if "=" in pair:
                        name, value = pair.split("=", 1)
                        self.driver.add_cookie({"name": name, "value": value})
                self.driver.get(url)
                try:
                    self.driver.get(url)
                except:
                    self.driver.execute_script("window.stop();")
                time.sleep(3)

            else:  # 使用本地文件 Cookie
                if os.path.exists(self.cookie_file):
                    # 直接注入本地 Cookie
                    self.update_status("加载本地 Cookie...", 10)
                    if not self._inject_cookies_from_file(self.driver, url):
                        raise Exception("本地 Cookie 文件损坏")
                    self.driver.refresh()
                else:
                    # 第一次使用，需要手动登录并保存
                    self.update_status("首次使用，请手动登录...", 10)
                    # 提示用户
                    self.root.after(0, lambda: messagebox.showinfo(
                        "手动登录",
                        "请在打开的浏览器窗口中手动登录。\n登录成功后，回到本程序点击“确定”。"
                    ))
                    self.driver.get(url)
                    # 阻塞线程直至用户点击消息框的“确定”——这里用 Event 同步
                    login_done = threading.Event()
                    self.root.after(0, lambda: (messagebox.showinfo(
                        "继续", "登录完成后请点击确定"
                    ), login_done.set()))
                    login_done.wait()   # 等待用户关闭提示框
                    # 登录后保存 Cookie
                    self._save_cookies_to_file()
                    self.update_status("Cookie 已保存，下次自动登录", 15)

            # 尝试关闭可能的弹窗 (Cookie 同意等)
            try:
                btns = self.driver.find_elements(By.XPATH,
                    "//*[contains(text(), 'Accept') or contains(text(), '接受') or contains(text(), '同意')]")
                if btns:
                    btns[0].click()
                    time.sleep(1)
            except:
                pass

            # 如果视频页面尚未加载好，再强制加载一次
            try:
                self.driver.get(url)
            except:
                self.driver.execute_script("window.stop();")
            time.sleep(5)

            # ---------------- 提取视频地址 ----------------
            self.update_status("正在提取视频链接...", 30)
            video_url = self._extract_video_url()
            if not video_url:
                raise Exception("未能从页面提取到视频地址，请确认页面结构或登录状态。")
            self.update_status(f"视频链接已抓到: {video_url[:80]}...", 40)

            # ---------------- 构造请求头 ----------------
            cookies = self.driver.get_cookies()
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            # 如果是粘贴模式，优先使用粘贴的 Cookie 字符串（可能包含 HttpOnly）
            if source == "paste" and self.cookie_str:
                cookie_str = self.cookie_str
            headers = {
                "User-Agent": self.driver.execute_script("return navigator.userAgent;"),
                "Referer": url,
                "Cookie": cookie_str
            }

            # ---------------- 下载并合并 ----------------
            output_file = os.path.join(save_dir, "video_output.mp4")
            self._download_m3u8(video_url, headers, output_file)

            self.update_status(f"下载完成！文件保存在: {output_file}", 100)
            messagebox.showinfo("成功", f"视频已保存到:\n{output_file}")

        finally:
            if self.driver:
                self.driver.quit()
                self.driver = None

    def _extract_video_url(self):
        """多种策略提取 m3u8 链接"""
        # 策略1：从 flashvars 等全局变量中找
        try:
            video_url = self.driver.execute_script("""
                for (let key in window) {
                    if (key.startsWith('flashvars_')) {
                        let obj = window[key];
                        let queue = [obj];
                        while (queue.length) {
                            let cur = queue.pop();
                            if (cur && typeof cur === 'object') {
                                if (cur.videoUrl) return cur.videoUrl;
                                if (cur.mediaDefinitions) {
                                    for (let d of cur.mediaDefinitions) {
                                        if (d.videoUrl) return d.videoUrl;
                                    }
                                }
                                for (let prop in cur) {
                                    if (typeof cur[prop] === 'object') queue.push(cur[prop]);
                                }
                            }
                        }
                    }
                }
                // 策略2：直接从 video 标签取
                let v = document.querySelector('video');
                if (v && v.src) return v.src;
                let s = document.querySelector('video source');
                if (s && s.src) return s.src;
                return null;
            """)
            if video_url:
                return video_url.replace("\\/", "/")
        except:
            pass

        # 策略3：从页面源码正则匹配 videoUrl 字段
        page_source = self.driver.page_source
        match = re.search(r'videoUrl["\']?\s*:\s*["\'](https?:\\?/\\?/[^"\']+)', page_source)
        if match:
            return match.group(1).replace("\\/", "/")
        return None

    def _download_m3u8(self, m3u8_url, headers, save_path):
        """递归解析 m3u8 并下载 ts 合并"""
        self.update_status("分析 m3u8 播放列表...", 50)
        resp = requests.get(m3u8_url, headers=headers)
        if resp.status_code == 410:
            raise Exception("链接已失效(410)，请重新运行并尽快下载。")
        resp.raise_for_status()
        content = resp.text

        # 如果是 master playlist，找到最高清子列表
        if "EXT-X-STREAM-INF" in content:
            lines = content.splitlines()
            child_url = None
            for i, line in enumerate(lines):
                if line.startswith("#EXT-X-STREAM-INF"):
                    child_relative = lines[i+1].strip()
                    child_url = urljoin(m3u8_url, child_relative)
                    break
            if not child_url:
                raise Exception("未找到子播放列表")
            self.update_status("进入真实分片列表...", 55)
            return self._download_m3u8(child_url, headers, save_path)

        # 已经是 media playlist，提取所有 .ts 链接
        base_url = m3u8_url.rsplit("/", 1)[0] + "/"
        ts_urls = []
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                if not line.startswith("http"):
                    line = urljoin(base_url, line)
                ts_urls.append(line)

        total = len(ts_urls)
        if total == 0:
            raise Exception("m3u8 内未找到任何视频片段")
        self.update_status(f"共 {total} 个片段，开始下载...", 60)

        # 临时存放 ts 的目录
        temp_dir = os.path.join(os.path.dirname(save_path), "temp_ts")
        os.makedirs(temp_dir, exist_ok=True)

        # 下载每个片段
        for i, ts_url in enumerate(ts_urls):
            for attempt in range(3):
                try:
                    r = requests.get(ts_url, headers=headers, timeout=15)
                    r.raise_for_status()
                    with open(os.path.join(temp_dir, f"{i:05d}.ts"), "wb") as f:
                        f.write(r.content)
                    break
                except Exception:
                    if attempt == 2:
                        raise Exception(f"下载片段 {i} 失败")
                    time.sleep(1)
            pct = 60 + int((i+1) / total * 30)
            self.update_status(f"下载片段 {i+1}/{total}", pct)

        # 合并
        self.update_status("合并视频文件中...", 92)
        with open(save_path, "wb") as out:
            for i in range(total):
                part_path = os.path.join(temp_dir, f"{i:05d}.ts")
                with open(part_path, "rb") as inf:
                    out.write(inf.read())
                os.remove(part_path)
        os.rmdir(temp_dir)
        self.update_status("合并完成", 100)

    def on_close(self):
        if self.driver:
            self.driver.quit()
        self.root.destroy()

if __name__ == "__main__":
    # ----- 强制把工作目录设为 exe 所在目录 -----
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))
    # -------------------
    root = tk.Tk()
    app = VideoDownloaderApp(root)
    root.mainloop()