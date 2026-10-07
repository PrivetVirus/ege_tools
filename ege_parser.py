import time
import os
import base64
import shutil
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ================= НАСТРОЙКИ =================
BASE_DIR = r"D:\EGE_Archive\Inf" 
TARGET_URL = "https://inf-ege.sdamgia.ru/test?a=cat"
TEMP_DOWNLOAD_DIR = os.path.join(BASE_DIR, "temp_downloads")

if not os.path.exists(TEMP_DOWNLOAD_DIR):
    os.makedirs(TEMP_DOWNLOAD_DIR)

# Очистка имен: теперь убирает и переносы строк (\n, \r)
def sanitize_name(name):
    clean_name = re.sub(r'[\\/*?:"<>|\n\r]', " ", name)
    clean_name = re.sub(r'\s+', " ", clean_name) # Убираем двойные пробелы
    return clean_name.strip()[:100]

def wait_for_download(download_dir, timeout=60):
    seconds = 0
    while seconds < timeout:
        files = os.listdir(download_dir)
        if any(f.endswith('.crdownload') for f in files):
            time.sleep(1)
            seconds += 1
        elif any(f.endswith('.pdf') for f in files):
            pdf_files = [os.path.join(download_dir, f) for f in files if f.endswith('.pdf')]
            if not pdf_files:
                continue
            latest_file = max(pdf_files, key=os.path.getctime)
            return latest_file
        else:
            time.sleep(1)
            seconds += 1
    return None

chrome_options = Options()
prefs = {
    "download.default_directory": TEMP_DOWNLOAD_DIR,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": False,  # <--- ДОБАВИТЬ ВОТ ЭТУ СТРОКУ
    "plugins.always_open_pdf_externally": True
}
chrome_options.add_experimental_option('prefs', prefs)
chrome_options.add_argument('--disable-features=SafeBrowsing')
print("🚀 Запускаем браузер...")
driver = webdriver.Chrome(options=chrome_options)
driver.set_page_load_timeout(300) # Даем 5 минут на прогрузку тяжелых страниц
driver.set_script_timeout(300)    # Даем 5 минут на рендеринг JS-скриптов (формул)
wait = WebDriverWait(driver, 15)

try:
    driver.get(TARGET_URL)
    print("⏳ Собираем структуру каталога...")
    time.sleep(3)

    catalog = {}

    topics = driver.find_elements(By.CSS_SELECTOR, "div.ConstructorForm-Topic")
    for topic in topics:
        try:
            topic_name_elem = topic.find_element(By.CSS_SELECTOR, "div.ConstructorForm-TopicName")
            driver.execute_script("arguments[0].scrollIntoView();", topic_name_elem)
            topic_name = sanitize_name(topic_name_elem.text)
            
            driver.execute_script("arguments[0].click();", topic_name_elem)
            time.sleep(0.5)

            catalog[topic_name] = {}
            # Ищем сразу теги <a> внутри раскрытого списка, чтобы не ловить пустые элементы
            subtopics_links = topic.find_elements(By.CSS_SELECTOR, "div.ConstructorForm-TopicSubs_open a")
            
            for sub_link in subtopics_links:
                try:
                    sub_name = sanitize_name(sub_link.text)
                    if not sub_name: # Страховка, если текст внутри другого тега
                        sub_name = sanitize_name(sub_link.find_element(By.XPATH, "..").text)
                    sub_url = sub_link.get_attribute("href")
                    
                    if sub_url and sub_name:
                        catalog[topic_name][sub_name] = sub_url
                except Exception:
                    continue # Если одна подтема сбоит, остальные не пострадают
        except Exception:
            continue

    total_tasks = sum(len(subs) for subs in catalog.values())
    print(f"✅ Структура собрана. Найдено тем: {len(catalog)}, всего подтем: {total_tasks}")

    task_counter = 1
    for topic_name, subtopics in catalog.items():
        topic_dir = os.path.join(BASE_DIR, topic_name)
        if not os.path.exists(topic_dir):
            os.makedirs(topic_dir)

        for sub_name, sub_url in subtopics.items():
            final_file_path = os.path.join(topic_dir, f"{sub_name}.pdf")
            
            if os.path.exists(final_file_path):
                print(f"⏩ Уже скачано: {sub_name}")
                task_counter += 1
                continue

            print(f"📥 [{task_counter}/{total_tasks}] Скачиваем: {topic_name} -> {sub_name}")
            driver.get(sub_url)

            try:
                print_link = wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, "Версия для печати")))
                driver.execute_script("arguments[0].click();", print_link)
                time.sleep(2)

                if len(driver.window_handles) > 1:
                    driver.switch_to.window(driver.window_handles[-1])

                cb_ans = driver.find_element(By.ID, "cb_ans")
                cb_sol = driver.find_element(By.ID, "cb_sol")
                
                if not cb_ans.is_selected():
                    driver.execute_script("arguments[0].click();", cb_ans)
                if not cb_sol.is_selected():
                    driver.execute_script("arguments[0].click();", cb_sol)
                
                time.sleep(1)

                # НОВЫЙ БЛОК: Генерация PDF силами ядра Chrome
                print(f"⚙️ Рендерим PDF ядром Chrome (обход зависаний)...")
                
                # Даем 5 секунд, чтобы все сложные формулы MathJax точно отрисовались на экране
                time.sleep(5) 
                
                # Приказываем Chrome собрать PDF из того, что он видит
                pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {
                    "printBackground": True,
                    "landscape": False, # Книжная ориентация лучше для уравнений
                    "marginTop": 0.5,
                    "marginBottom": 0.5,
                    "marginLeft": 0.5,
                    "marginRight": 0.5,
                })

                # Напрямую записываем байты в готовый файл на твою флешку
                with open(final_file_path, "wb") as f:
                    f.write(base64.b64decode(pdf_data['data']))

                if len(driver.window_handles) > 1:
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

            except Exception as e:
                print(f"⚠️ Ошибка обработки {sub_name}: {e}")
                if len(driver.window_handles) > 1:
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

            task_counter += 1

    print("🎉 Все задания успешно сохранены в папки!")

finally:
    driver.quit()
    if os.path.exists(TEMP_DOWNLOAD_DIR) and not os.listdir(TEMP_DOWNLOAD_DIR):
        os.rmdir(TEMP_DOWNLOAD_DIR)