import os
import sys
import time
import base64
import hashlib
import re
import tkinter as tk
from tkinter import messagebox
from playwright.sync_api import sync_playwright

# ================= 打包后强制弹出 CMD 控制台窗口（实时显示运行日志） =================
# 背景：若 EXE 是以 --noconsole/--windowed 方式打包的，程序运行时没有任何控制台窗口，
#       print 打印的日志"无处可去"，看起来就像纯后台运行，无法观察刷课进度。
# 方案：启动时先问 Windows"我有没有控制台窗口"，没有就主动申请一个新的 CMD 窗口，
#       再把 print 使用的 sys.stdout 重定向到这个新窗口；若本来就有控制台则什么都不做。
if getattr(sys, 'frozen', False):  # sys.frozen 只有被 PyInstaller 打包成 EXE 后才存在，直接跑 .py 时为 False
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # 调用 Windows 系统API（kernel32.dll）
        if kernel32.GetConsoleWindow() == 0:  # 返回 0 说明当前进程还没有控制台窗口
            kernel32.AllocConsole()  # 向系统申请一个新的 CMD 控制台窗口（黑框）
            kernel32.SetConsoleOutputCP(65001)  # 把控制台输出编码切到 UTF-8，避免中文乱码
            kernel32.SetConsoleTitleW("和学在线自动挂机 - 运行日志")  # 给黑框窗口设置标题
            # 把标准输出/错误流重新指向新控制台的显示缓冲区（CONOUT$ 是 Windows 保留设备名）
            # buffering=1 表示行缓冲：每 print 一行立刻显示一行，保证日志实时刷新
            sys.stdout = open('CONOUT$', 'w', buffering=1, encoding='utf-8', errors='replace')
            sys.stderr = open('CONOUT$', 'w', buffering=1, encoding='utf-8', errors='replace')
    except Exception:
        pass  # 万一分配失败也不影响主流程，顶多没有日志窗口

# 防止打包 EXE 后控制台输出 emoji 时因 GBK 编码报错
try:
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass

# ================= 配置区 =================
CONCURRENT_TABS = 5  # 并发视频数量

# =========================================

# --- 辅助弹窗函数 ---
def show_error_and_exit(msg):
    root = tk.Tk()
    root.withdraw() # 隐藏主窗口
    root.attributes("-topmost", True)
    messagebox.showerror("安全提示", msg)
    root.destroy()
    sys.exit()

def show_info_and_exit(msg):
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    messagebox.showinfo("学习完成", msg)
    root.destroy()
    sys.exit()

def start_learning():
    # 针对打包 EXE 后的路径重定向
    if getattr(sys, 'frozen', False):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(sys._MEIPASS, 'pw-browsers')

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,  # 彻底隐藏浏览器
            args=[
                '--start-maximized', 
                '--mute-audio',
                '--disable-background-timer-throttling', 
                '--disable-backgrounding-occluded-windows' 
            ]
        )
        context = browser.new_context(no_viewport=True) 
        main_page = context.new_page()

        print("🌍 正在后台加载数据，请稍候...")
        main_page.goto("http://login.hexuezx.cn/indexOld.html?redirected=true")
        
        try:
            main_page.locator('#tab-qrcode').click()
            main_page.wait_for_timeout(1000)
        except:
            pass

        # 提取初始二维码
        qr_img_locator = main_page.locator('#pane-qrcode img')
        qr_img_locator.wait_for(state='visible', timeout=10000)
        b64_src = qr_img_locator.get_attribute('src')
        
        if not (b64_src and "base64," in b64_src):
            print("❌ 获取二维码失败。")
            browser.close()
            return

        # ================= 自定义白色扫码窗口 =================
        qr_root = tk.Tk()
        qr_root.title("扫码登录")
        qr_root.geometry("500x500")
        qr_root.config(bg="white")
        qr_root.attributes("-topmost", True) # 窗口置顶，防止被挡住
        qr_root.resizable(True, True)

        lbl_qr = tk.Label(qr_root, bg="white")
        lbl_qr.pack(expand=True)

        def update_qr_image(base64_str):
            img_data = base64_str.split(",")[1]
            img = tk.PhotoImage(data=img_data)
            lbl_qr.config(image=img)
            lbl_qr.image = img # 必须保留引用，否则图片不显示

        update_qr_image(b64_src)

        # 轮询检测登录与二维码刷新
        login_success = False
        print("⏳ 请使用【和学在线APP】扫描屏幕上的二维码...")
        
        while True:
            # 刷新 UI，防止窗口无响应卡死
            try:
                qr_root.update()
            except tk.TclError:
                # 窗口被用户手动关闭了
                break
                
            if main_page.locator('.home').count() > 0:
                login_success = True
                break
            
            # 检测超时
            delay_box = main_page.locator('.delayTime')
            if delay_box.count() > 0 and delay_box.is_visible():
                main_page.locator('.delayTime .blue').click()
                main_page.wait_for_timeout(1500)
                new_b64 = main_page.locator('#pane-qrcode img').get_attribute('src')
                if new_b64 and "base64," in new_b64:
                    update_qr_image(new_b64)
            
            time.sleep(0.1) # 短暂休眠，防 CPU 占用过高

        # 销毁扫码窗口
        try:
            qr_root.destroy()
        except:
            pass

        if not login_success:
            print("🚪 登录未完成，软件退出。")
            browser.close()
            return
            
        print("✅ 登录成功！正在进行安全校验...")

        # ================= 安全校验：学号 MD5 绑定 =================
        try:
            print("⏳ 正在等待服务器同步个人学号数据...")
            stu_id = None
            full_info_text = ""
            
            # 轮询等待数据加载（最多等待 15 秒）
            for _ in range(15):
                main_page.wait_for_timeout(1000)  # 等待 1 秒让 Vue 渲染数据
                
                if main_page.locator(".infoText").count() > 0:
                    # 获取第一块匹配的 infoText 里的全部文本
                    full_info_text = main_page.locator(".infoText").first.text_content()
                    
                    # 匹配“学号:”后面跟着至少 10 位以上的数字（防止抓到半截数据）
                    stu_id_match = re.search(r'学号:\s*(\d{10,})', full_info_text)
                    
                    if stu_id_match:
                        stu_id = stu_id_match.group(1)
                        break  # 只要找到了学号，立刻跳出等待循环！
            
            if not stu_id:
                print(f"⚠️ 调试信息：最终抓取到的文本为：\n{full_info_text}")
                raise Exception("已超时 15 秒，未能获取到学号，可能是网络卡顿或账号数据异常。")
                
            print(f"🔒 成功提取到学号: {stu_id}")
            
                
        except Exception as e:
            try:
                browser.close()
            except:
                pass
            show_error_and_exit(f"安全校验失败: \n{e}")

        # ================= 校验通过，开始核心刷课逻辑 =================
        #
        # 【"看完一个视频自动播下一个"的整体实现思路】共三层循环接力：
        #   第 1 层 for ：一门课一门课地处理（course_index 从 0 到 total_courses-1）
        #   第 2 层 for ：把一门课里所有"未完成的视频"按每批 5 个（CONCURRENT_TABS）分批
        #   批内 while  ：这批 5 个视频同时在各自的浏览器标签页里播放，守护循环每 5 秒
        #                 巡检一次，谁播完就关掉谁的标签页；等这一批【全部】播完
        #                 （active_pages 名单清空）while 才退出 → 第 2 层 for 自动切出
        #                 下一批 5 个视频接着挂机播放。
        #                 即：批内 5 个并发播放，批与批之间按顺序自动接力 → 自动连播。
        #   一门课的所有批次播完后回到首页，第 1 层 for 进入下一门课，如此往复，
        #   直到账号内所有课程的视频全部刷完。
        #
        # CSS 选择器：ElementUI 的主要按钮(primary)中，按钮文本为「课程学习」的元素。
        # 首页上每一门课程都对应一个这样的按钮，它是进入该课程详情页的入口。
        btn_selector = 'button.el-button--primary:has-text("课程学习")'
        # 最多等 10 秒，直到页面上出现第一个「课程学习」按钮（确保课程列表已渲染完成）
        main_page.wait_for_selector(btn_selector, timeout=10000)
        # 统计首页一共有多少个「课程学习」按钮 → 就是本账号需要刷的课程总数
        total_courses = len(main_page.query_selector_all(btn_selector))
        print(f"📚 首页共检测到 {total_courses} 门课程需要学习。")

        # 一门课都没有：直接弹窗收工
        if total_courses == 0:
            browser.close()
            show_info_and_exit("当前账号没有需要学习的课程！")

        # ---------- 第 1 层循环：逐门课程处理 ----------
        for course_index in range(total_courses):
            print(f"\n==================================================")
            print(f"🚀 正在后台处理第 {course_index + 1} / {total_courses} 门课程...")
            print(f"==================================================")

            # 每次回到首页后都要重新等按钮出现（上一轮结束时刷新过页面）
            main_page.wait_for_selector(btn_selector)
            # 重新抓一遍按钮列表：页面刷新后 DOM 全是新元素，上一轮的旧引用已失效
            current_buttons = main_page.query_selector_all(btn_selector)
            # 点击第 course_index 个「课程学习」按钮 → 进入这门课的学习详情页
            current_buttons[course_index].click()
            # 等到网络请求全部结束（章节列表是 Vue 异步加载的），再兜底多等 3 秒
            main_page.wait_for_load_state("networkidle")
            main_page.wait_for_timeout(3000)

            # ---------- 展开所有折叠的章节面板 ----------
            # 每个章节是一个 el-collapse-item 折叠面板，可点击的标题栏 class 为 el-collapse-item__header
            headers = main_page.locator('.el-collapse-item__header')
            for i in range(headers.count()):
                header = headers.nth(i)
                # 面板展开后 class 里会带 is-active；没带说明还折叠着，点一下展开它
                if "is-active" not in (header.get_attribute("class") or ""):
                    try:
                        header.click()
                        main_page.wait_for_timeout(300)
                    except: pass

            # ---------- 收集本课程所有"未完成的视频"任务 ----------
            # 真实网页结构（以用户提供的 HTML 为准）：
            #   el-collapse-item（章节折叠面板，可展开/收起）
            #    ├─ 折叠头 div.collapse_title
            #    │    ├─ span.title_span            → 章节名（如"1.1计算机系统的概率和发展"）
            #    │    └─ div.progress_box > p       → 章节进度
            #    │        分式课程显示"41/16（分钟）"（已学分钟/总分钟，中文括号、带换行缩进）
            #    └─ 折叠体 ul.collapse_content_box > li.collapse_content_list（每个小节任务）
            #         ├─ span.list_icon（视频/文档）+ span.list_text（任务名，如 xxx.mp4）
            #         └─ div.progress_box > p → ⚠️ 只显示"已学分钟数"（如"41.2334 (分钟)"），
            #            没有"/总时长"！所以单个视频学没学完，只能看章节头上的分式
            #
            # 判定策略：
            #   · 章节头出现"已学/总"分式 → 分式课程：前 ≥ 后 → 整章学完跳过；未学完的章节
            #     收集其中全部视频任务，交给挂机守护循环播放到结束
            #   · 没有任何章节头分式 → 百分比课程：按 li 行内的 el-progress 进度条判定

            # ── 先探测本课程是不是"分式进度"课程：任意章节头的 progress_box p 里含 "x/y" ──
            frac_headers = main_page.locator('div.collapse_title .progress_box p')
            is_fraction_course = False
            for k in range(frac_headers.count()):
                if re.search(r'\d+\s*/\s*\d+', frac_headers.nth(k).inner_text()):
                    is_fraction_course = True
                    break

            tasks_pool = []  # 待刷任务池：只装"还没学完的视频"类任务

            if is_fraction_course:
                # ══════════ 分式课程分支（极少数课程） ══════════
                print("   ℹ️ 检测到分式进度课程（章节头显示 已学/总 分钟数），按章节分式判定完成状态。")
                chapters = main_page.locator('.el-collapse-item')
                for ci in range(chapters.count()):
                    chapter = chapters.nth(ci)
                    try:
                        # 章节名（.title_span 在折叠头 collapse_title 里）
                        t_loc = chapter.locator('.collapse_title .title_span')
                        ch_name = t_loc.first.inner_text().strip() if t_loc.count() > 0 else f"章节{ci + 1}"
                        # 章节头的分式进度，如 "41/16（分钟）"
                        f_loc = chapter.locator('.collapse_title .progress_box p')
                        f_text = f_loc.first.inner_text().strip() if f_loc.count() > 0 else ""
                        # 提取"/"两侧数字，支持小数（如 41.25/16）
                        m = re.search(r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)', f_text) if f_text else None
                        if m and float(m.group(1)) >= float(m.group(2)):
                            # 规则："/"前（已学分钟）>= "/"后（总分钟）→ 整章学完，整章跳过
                            print(f"   ✅ [{ci + 1}] 章节「{ch_name}」已学完（{f_text}），跳过整章")
                            continue
                        if f_text:
                            print(f"   📖 [{ci + 1}] 章节「{ch_name}」未学完（{f_text}），开始收集该章视频任务...")
                        else:
                            print(f"   ⚠️ [{ci + 1}] 章节「{ch_name}」头上没有分式进度文本，按未学完处理")
                        # 收集该章节折叠体内的小节任务（li 在 el-collapse-item__wrap 折叠体里）
                        lis = chapter.locator('li.collapse_content_list')
                        for li_i in range(lis.count()):
                            li = lis.nth(li_i)
                            try:
                                # 类型文字（视频/文档/测验…），只处理视频
                                icon = li.locator('.list_icon')
                                t_type = icon.first.inner_text().strip() if icon.count() > 0 else ""
                                if "视频" not in t_type:
                                    continue
                                # 任务名
                                name_loc = li.locator('.list_text')
                                name = name_loc.first.inner_text().strip() if name_loc.count() > 0 else f"{ch_name}-任务{li_i + 1}"
                                # li 行的 p 只有已学分钟数（没有总时长），无法单独判定是否学完，
                                # 一律加入任务池交给守护循环：打开视频播放到结束为止
                                studied_loc = li.locator('.progress_box p')
                                studied_text = studied_loc.first.inner_text().strip() if studied_loc.count() > 0 else ""
                                print(f"   🔍 [{ci + 1}-{li_i + 1}] {name} | 类型:{t_type} | 已学:「{studied_text}」→ 待刷")
                                tasks_pool.append({'item': li, 'name': name, 'page': None})
                            except Exception as e:
                                print(f"   ⚠️ 章节「{ch_name}」第 {li_i + 1} 个小节识别失败（已跳过）: {e}")
                    except Exception as e:
                        print(f"   ⚠️ 第 {ci + 1} 个章节识别失败（已跳过）: {e}")
            else:
                # ══════════ 百分比课程分支（绝大多数课程，原有逻辑） ══════════
                items = main_page.locator('li.collapse_content_list')
                total_items = items.count()
                print(f"📋 本课程共 {total_items} 个小节，开始逐个识别任务与进度...")
                for i in range(total_items):
                    item = items.nth(i)
                    try:
                        # 任务名称（列表里显示的文字，用于日志展示）
                        name = item.locator('.list_text').first.inner_text().strip()
                        # 任务类型文字（视频 / 文档 / 测验…），我们只处理视频
                        t_type = item.locator('.list_icon').first.inner_text().strip()
                        if "视频" not in t_type:
                            continue  # 非视频任务直接跳过，不进入任务池

                        # ElementUI 进度条文本，如 "100%"。
                        # 关键：必须先用 count() 判断元素是否存在，再取文本！
                        # 若对不存在的元素直接调 inner_text()，Playwright 会傻等 30 秒才报错，
                        # 报错又被 except 吞掉 → 这正是之前"分式课程卡住不动"的元凶。
                        pct = item.locator('.el-progress-bar__innerText')
                        pct_text = pct.first.inner_text().strip() if pct.count() > 0 else ""
                        done = "100%" in pct_text  # 进度条显示 100% → 已学完

                        # 🔍 诊断打印：把每个视频任务抓到的原始进度文本打出来
                        print(f"   🔍 [{i + 1}] {name} | 类型:{t_type} | 百分比:「{pct_text}」→ {'已完成' if done else '待刷'}")

                        # 未学完的视频 → 加入任务池；page 字段先占位为 None
                        if not done:
                            tasks_pool.append({'item': item, 'name': name, 'page': None})
                    except Exception as e:
                        # 单个小节识别失败不再静默跳过，打印具体原因方便排查
                        print(f"   ⚠️ 第 {i + 1} 个小节识别失败（已跳过）: {e}")

            print(f"🎯 共有 {len(tasks_pool)} 个未完成的【视频】待处理。")

            # ---------- 第 2 层循环：把任务池按每批 5 个分批接力 ----------
            if len(tasks_pool) > 0:
                # range(0, N, 5) 产生 0,5,10,15...，每次从任务池切出 5 个组成一批
                for i in range(0, len(tasks_pool), CONCURRENT_TABS):
                    # 本批要处理的任务（最后一批可能不足 5 个）
                    current_batch = tasks_pool[i : i + CONCURRENT_TABS]
                    active_pages = []  # 本批中"已成功打开并正在播放"的标签页名单
                    print(f"\n📦 === 开启后台并发处理 ({len(current_batch)} 个并发) ===")

                    # ---------- 批内第一步：把这批视频逐个"挂起"（各开一个新标签页播放） ----------
                    for task in current_batch:
                        # 先打印要挂起谁：如果卡在这一步，日志能立刻暴露卡在哪个任务上
                        print(f"▶️ 正在挂起: {task['name']} ...")
                        # 先把该任务滚动到可视区域，否则元素可能点不到（限时 5 秒，防止卡死）
                        try:
                            task['item'].scroll_into_view_if_needed(timeout=5000)
                        except Exception as e:
                            print(f"   ⚠️ [{task['name']}] 滚动到任务位置失败: {e}")
                        try:
                            # 点击任务文字后，网站会在【新标签页】里打开视频播放器；
                            # expect_page 上下文管理器负责捕获这个即将弹出的新页面
                            with context.expect_page(timeout=10000) as new_page_info:
                                # 点击目标兼容两种结构：百分比课程点 .list_text，分式课程点 .title_span
                                click_loc = task['item'].locator('.list_text')
                                if click_loc.count() == 0:
                                    click_loc = task['item'].locator('.title_span')
                                click_loc.first.click(timeout=5000)

                            # 拿到新标签页对象，并给该页面设置全局 5 秒超时：
                            # 之后页面上任何操作最多等 5 秒，绝不无限卡死
                            t_page = new_page_info.value
                            t_page.set_default_timeout(5000)
                            task['page'] = t_page
                            active_pages.append(task)
                            # 打印新标签页网址，能看出网站到底打开了什么页面
                            print(f"🔗 后台已挂起: {task['name']} （页面: {t_page.url[:80]}）")

                            # 等 2 秒让页面里的 video.js 播放器初始化完成
                            t_page.wait_for_timeout(2000)
                            # 尝试点播放器中央的大播放按钮；个别页面没有该按钮就跳过
                            try: t_page.locator('.vjs-big-play-button').click(timeout=3000)
                            except: pass
                            # 兜底：直接执行 <video> 元素的原生 play() 方法强制开播
                            try:
                                t_page.locator('video').first.evaluate("node => node.play()")
                            except Exception as e:
                                print(f"   ⚠️ [{task['name']}] 强制播放失败（页面可能没有 video 元素）: {e}")
                        except Exception as e:
                            # 点了却没弹出新标签页 → 打印原因，放弃该任务继续下一个
                            print(f"❌ 挂载任务 [{task['name']}] 失败: {e}")

                    # ---------- 批内第二步：守护循环，谁播完就关谁，全批播完才放行 ----------
                    # 只要这批里还有任何一页在播，while 就不退出（每 5 秒巡检一轮）
                    while len(active_pages) > 0:
                        time.sleep(5)
                        # 遍历 active_pages 的副本[:]：循环体内要 remove 元素，直接遍历原列表会漏项
                        for task in active_pages[:]:
                            t_page = task['page']
                            name = task['name']
                            try:
                                # 把标签页切到前台：网站要求页面处于激活状态，播放时长才会被计入进度
                                t_page.bring_to_front()

                                # 页面里连 <video> 元素都没有 → 播放器结构不同或还没加载出来。
                                # 以前这种情况会在 evaluate() 里傻等 30 秒再被静默吞掉，表现为"卡住不动"；
                                # 现在先 count() 判存在（瞬间返回），并打印含网址的诊断信息。
                                if t_page.locator('video').count() == 0:
                                    print(f"   ⚠️ [{name}] 页面未检测到 <video> 播放器 (URL: {t_page.url[:80]})，5 秒后再查...")
                                    continue

                                # 判断播放器是否已进入"播完"状态：video.js 播完会给容器加 vjs-ended 类
                                ended = t_page.locator('.video-js.vjs-ended').count() > 0
                                # 读取 <video> 的当前播放秒数和总时长（在浏览器里执行 JS 取值）
                                cur = t_page.locator('video').first.evaluate("node => node.currentTime")
                                dur = t_page.locator('video').first.evaluate("node => node.duration")

                                # 打印实时进度，让你能随时看到每个视频刷到哪一秒了
                                if dur and dur > 0:
                                    print(f"   📺 {name} 进度: {int(cur)}/{int(dur)} 秒")
                                else:
                                    # 读不到时长说明视频还没真正开播（比如卡在加载/被暂停）
                                    print(f"   ⏸ [{name}] 暂时读不到播放进度，尝试续播...")

                                # 判定播完的两个条件（满足其一即可）：
                                #   1) 播放器带了 vjs-ended 播完标记
                                #   2) 播放进度已逼近总时长（相差不到 1 秒，防止 ended 标记偶尔检测不到）
                                if ended or (dur and dur > 0 and cur >= dur - 1):
                                    print(f"🎉 视频完成: {name}！等待清理释放内存...")
                                    # 再等 3 秒，给页面留出把"学习时长"上报给服务器的时间
                                    t_page.wait_for_timeout(3000)
                                    # 点播放器右上角的关闭按钮，走网站自己的正常关闭流程
                                    try:
                                        close_btn = t_page.locator('.video-close')
                                        if close_btn.count() > 0 and close_btn.is_visible():
                                            close_btn.click()
                                            t_page.wait_for_timeout(1000)
                                    except: pass
                                    # 彻底关闭这个标签页，释放内存
                                    t_page.close()
                                    # 从"正在播放"名单移除；等整批全播完（名单清空）while 才结束
                                    active_pages.remove(task)
                                else:
                                    # 还没播完：若中途被暂停/卡住，再强制 play() 一次续播
                                    try: t_page.locator('video').first.evaluate("node => node.play()")
                                    except: pass
                            except Exception as e:
                                # 巡检出错不再静默吞掉，打印具体原因（页面被网站关掉/跳转等）
                                print(f"   ⚠️ [{name}] 巡检出错: {e}")

            # 走到这里说明这门课的所有批次都播完了 → 第 1 层 for 进入下一门课
            print(f"🔙 第 {course_index + 1} 门课程处理完毕，正在切换下一门...")
            # 回到课程首页，让下一轮循环能重新拿到并点击下一门课的「课程学习」按钮
            main_page.goto("http://student.hexuezx.cn/#/home")
            main_page.wait_for_selector(btn_selector)
            main_page.wait_for_timeout(2000)

        # ================= 核心任务全部完毕，弹出提示框并自动关机 =================
        browser.close()
        # print("💤 电脑将在 60 秒后自动关机（如需取消，请在命令行执行：shutdown /a）")
        # os.system("shutdown /s /t 60")
        show_info_and_exit("恭喜！账号内所有课程的视频任务已全部挂机通关！\n\n电脑将在 60 秒后自动关机。\n如需取消关机，请在命令行执行：shutdown /a")

if __name__ == "__main__":
    start_learning()