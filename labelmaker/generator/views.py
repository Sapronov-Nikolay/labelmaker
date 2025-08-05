from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.core.files.storage import FileSystemStorage
from django.conf import settings
import pandas as pd
import os
import logging
import json
from .utils import get_legal_entities, update_legal_entity, remove_legal_entity, load_legal_entities, save_legal_entities
from textwrap import shorten
from .forms import UploadForm, HeaderSelectForm, ColumnSelectForm, EditDataForm, LabelSettingsForm
from django.forms import formset_factory
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

# Инициализация логгера для записи событий
logger = logging.getLogger(__name__)


# ===========================================================
# ГЛОБАЛЬНЫЕ КОНСТАНТЫ ДЛЯ ДИЗАЙНА ЭТИКЕТОК
# ===========================================================

# Размеры страницы и отступы
PAGE_WIDTH = 58 * mm       # Ширина этикетки (58 мм)
PAGE_HEIGHT = 40 * mm      # Высота этикетки (40 мм)
MARGIN = 0.2 * mm            # Отступ от края страницы
PADDING_RIGHT = 5 * mm     # Правый отступ для текста
PADDING_LEFT = 5 * mm      # Левый отступ для текста

# Размеры шрифтов
COMPANY_FONT_SIZE = 8.2    # Размер шрифта для названия компании
PRODUCT_FONT_SIZE = 7.4    # Размер шрифта для названия товара
ARTICLE_FONT_SIZE = 7.5    # Размер шрифта для артикула
EXTRA_FONT_SIZE = 8        # Размер шрифта для дополнительной информации

# Параметры штрих-кода (одинаковые для всех режимов генерации)
BARCODE_HEIGHT = 8.3 * mm        # Высота штрих-кода
BARCODE_BAR_WIDTH = 0.75       # Толщина штрихов (меньше = тоньше)
BARCODE_TEXT_SIZE = 9          # Размер шрифта для цифр под штрих-кодом
BARCODE_TOP_MARGIN = 12 * mm   # Отступ штрих-кода от верхнего края
BARCODE_TEXT_OFFSET = 4 * mm   # Отступ текста от штрих-кода
AFTER_BARCODE_SPACE = 17 * mm  # Отступ после блока штрих-кода

# Дополнительные параметры вёрстки
LINE_SPACING = 1 * mm          # Универсальный межстрочный интервал
PRODUCT_SIDE_PADDING = 5 * mm  # Боковые отступы для названия товара

# Дополнительные отступы для элементов (необязательные, могут использоваться в будущем)
ELEMENT_OFFSETS = {
    'after_barcode': 3 * mm,
    'after_company': 1.5 * mm,
    'after_product': 1 * mm,
    'after_article': 1 * mm
}

# Путь для сохранения шаблонов этикеток
TEMPLATES_DIR = os.path.join(settings.MEDIA_ROOT, 'patterns')

# ===========================================================
# VIEW-ФУНКЦИИ
# ===========================================================

def upload_file(request):
    # 1. Обработка всех действий с юрлицами
    if request.method == 'POST' and 'entity_action' in request.POST:
        action = request.POST['entity_action']
        
        # Удаление
        if action == 'delete':
            remove_legal_entity(request.POST['delete_entity'])
            return redirect('upload_file')
            
        # Добавление нового
        elif action == 'add':
            new_entity = request.POST.get('new_entity', '').strip()
            if new_entity:
                update_legal_entity(new_entity, add_to_list=True)
            return redirect('upload_file')
            
        # Сохранение/использование
        elif action in ['save', 'update']:
            entity = request.POST.get('legal_entity', '').strip()
            if entity:
                update_legal_entity(entity, add_to_list=(action == 'save'))
            return redirect('upload_file')
    """
    Обработка загрузки Excel-файла с выбором режима работы.
    Определяет тип генерации (массовая печать или создание шаблонов).
    """
    # Очищаем сессию при новой загрузке
    request.session.flush()
    
    if request.method == 'POST':
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            # Определяем выбранный режим работы
            if form.cleaned_data.get('template_file'):  # Исправлено на использование метода
                file = request.FILES['template_file']
                request.session['is_template_mode'] = True
            else:
                file = request.FILES['bulk_file']
                request.session['is_template_mode'] = False

            # Сохраняем оригинальное имя файла для отображения
            original_filename = file.name
            request.session['file_display_name'] = original_filename

            # Сохраняем файл во временную папку
            fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'temp'))

            # Удаляем все файлы из папки temp перед сохранением нового
            try:
                for existing_file in fs.listdir('')[1]:
                    fs.delete(existing_file)
            except Exception as e:
                logger.error(f"Ошибка очистки temp: {str(e)}")
                
            # Сохраняем файл
            try:
                saved_filename = fs.save(original_filename, file)
                request.session['excel_path'] = fs.path(saved_filename)
                logger.info(f"Файл сохранен: {saved_filename}")  # Логирование сохраненного файла
                logger.info("Редирект на select_header")  # Логирование редиректа
                return redirect('select_header')  # Убедитесь, что редирект здесь
            except Exception as e:
                logger.error(f"Ошибка сохранения файла: {str(e)}")
                form.add_error(None, "Ошибка сохранения файла")
    else:
        form = UploadForm()

    #  Формируем контекст
    legal_data = get_legal_entities()
    context = {
        'form': form,
        'legal_entities': legal_data['all'], #  Список всех юрлиц
        'current_entity': legal_data['current'], #  Текущее выбранное
    }
    
    return render(request, 'generator/upload.html', context)

def select_header(request):
    """
    Выбор строки с заголовками в Excel-файле.
    Пользователь указывает номер строки, содержащей названия колонок.
    """
    if 'excel_path' not in request.session:
        return redirect('upload_file')
    
    if request.method == 'POST':
        form = HeaderSelectForm(request.POST)
        if form.is_valid():
            # Сохраняем номер строки заголовков (индекс начинается с 0)
            request.session['header_row'] = form.cleaned_data['header_row'] - 1
            return redirect('select_columns')
    else:
        form = HeaderSelectForm()

    # Получаем имя файла из пути в сессии
    excel_path = request.session.get('excel_path', '')
    file_name = os.path.basename(excel_path) if excel_path else 'Файл не выбран'

    # Контекст с информацией о файле и режиме
    context = {
        'form': form,
        'file_name': request.session.get('file_display_name', 'Файл не выбран'),
        'is_template_mode': request.session.get('is_template_mode', False)
    }
    return render(request, 'generator/select_header.html', context)



def select_columns(request):
    """
    Выбор колонок, которые будут использоваться для генерации этикеток.
    Показывает предпросмотр данных для помощи пользователю.
    """
    if 'excel_path' not in request.session or 'header_row' not in request.session:
        return redirect('upload_file')
    
    # Чтение Excel-файла с учетом выбранной строки заголовков
    df = pd.read_excel(request.session['excel_path'], header=request.session['header_row'])
    columns = df.columns.tolist()
    sample_data = df.head(5).to_dict('records')
    
    if request.method == 'POST':
        form = ColumnSelectForm(request.POST, columns=columns)
        if form.is_valid():
            # Сохраняем выбранные колонки
            selected_columns = [col for col in columns if form.cleaned_data[col]]
            request.session['selected_columns'] = selected_columns
            return redirect('label_settings')
    else:
        # Создаём форму с предвыбранными полями
        initial ={}
        default_columns = ['Баркод', 'Наименование', 'Артикул', 'Цвет']
        for col in columns:
            initial[col] = col in default_columns
        form = ColumnSelectForm(columns=columns, initial=initial)
    
    context = {
        'form': form, 
        'columns': columns, 
        'sample_data': sample_data,
        'file_name': request.session.get('file_display_name', 'Файл не выбран'),
        'is_template_mode': request.session.get('is_template_mode', False)
    }
    return render(request, 'generator/select_columns.html', context)



def label_settings(request):
    """
    Настройка соответствия колонок данным для этикетки.
    Пользователь выбирает какие колонки использовать для штрих-кода, названия и артикула.
    """
    selected_columns = request.session.get('selected_columns', [])
    
    if request.method == 'POST':
        form = LabelSettingsForm(request.POST, columns=selected_columns)
        if form.is_valid():
            # Сохраняем выбранные соответствия колонок
            request.session['column_mapping'] = {
                'barcode': form.cleaned_data['barcode_column'],
                'product_name': form.cleaned_data['product_name_column'],
                'article': form.cleaned_data['article_column'],
                'size': form.cleaned_data['size_column']  # Добавляем размер
            }
            return redirect('edit_data')
    else:
        form = LabelSettingsForm(columns=selected_columns)
    
    context = {
        'form': form,
        'file_name': request.session.get('file_display_name', 'Файл не выбран'),
        'is_template_mode': request.session.get('is_template_mode', False)
    }
    return render(request, 'generator/label_settings.html', context)



def edit_data(request):
    """Форма редактирования данных"""
    if not all(key in request.session for key in ['excel_path', 'header_row', 'selected_columns', 'column_mapping']):
        return redirect('upload_file')

    # Чтение и обработка данных из Excel
    df = pd.read_excel(request.session['excel_path'], header=request.session['header_row'])
    raw_data = df[request.session['selected_columns']].to_dict('records')
    
    size_column = request.session['column_mapping'].get('size')

    # Группировка данных с подсчетом количества
    grouped = {}
    for item in raw_data:
        article = str(item.get(request.session['column_mapping']['article'], '')).strip().lower()
        barcode = str(item.get(request.session['column_mapping']['barcode'], '')).strip().lower()
        color = str(item.get('Цвет', '')).strip().lower()
        size = str(item.get(size_column, '')).strip().lower() if size_column else ''

        key = f"{article}|{barcode}|{color}|{size}"
        if key not in grouped:
            grouped[key] = {
                'data': item.copy(),
                'quantity': 0  # Начинаем с 0
            }
            if size_column:
                grouped[key]['data']['Размер'] = size
        
        # Увеличиваем счетчик для каждого найденного товара
        grouped[key]['quantity'] += 1

    # Умножаем количество на 2 (по 2 этикетки на товар) только в режиме массовой печати
    if not request.session.get('is_template_mode', False):
        for key in grouped:
            grouped[key]['quantity'] *= 2

    # Создаем формсет
    EditFormSet = formset_factory(EditDataForm, extra=0)
    
    if request.method == 'POST':
        formset = EditFormSet(request.POST)
        
        if formset.is_valid():
            # Определяем режим генерации из скрытого поля
            generation_mode = request.POST.get('generation_mode', 'bulk')
            is_template_mode = (generation_mode == 'template')
            
            # Обновляем данные из формы
            for i, (key, values) in enumerate(grouped.items()):
                form_data = formset[i].cleaned_data
                grouped[key]['data']['Цвет'] = form_data.get('color', '')
                if size_column:
                    grouped[key]['data']['Размер'] = form_data.get('size', '')
                
                # Для шаблонов всегда 1, для массовой - сохраняем введенное значение (включая 0)
                if is_template_mode:
                    grouped[key]['quantity'] = 1
                else:
                    grouped[key]['quantity'] = form_data.get('quantity', grouped[key]['quantity'])

            # Фильтруем данные, удаляя записи с нулевым количеством только в режиме массовой печати
            if not is_template_mode:
                processed_data = [item for item in grouped.values() if item['quantity'] > 0]
            else:
                processed_data = list(grouped.values())

            # Сохраняем данные в сессии
            request.session['processed_data'] = processed_data
            request.session['is_template_mode'] = is_template_mode
            request.session.modified = True
            
            return redirect('generate_pdf')
    else:
        # Устанавливаем начальное количество
        initial_data = []
        for item in grouped.values():
            if request.session.get('is_template_mode', False):
                initial_data.append({'quantity': 1})  # Для шаблонов всегда 1
            else:
                initial_data.append({'quantity': item['quantity']})  # Для массовой - сохраненное значение (×2 по умолчанию)
        
        formset = EditFormSet(initial=initial_data)

    # Подготавливаем данные для отображения
    grouped_list = [(k, {'data': v['data'], 'form': f}) for (k, v), f in zip(grouped.items(), formset)]
    
    context = {
        'formset': formset,
        'grouped_list': grouped_list,
        'selected_columns': request.session['selected_columns'],
        'column_mapping': request.session['column_mapping'],
        'file_name': request.session.get('file_display_name', 'Файл не выбран'),
        'is_template_mode': request.session.get('is_template_mode', False)
    }
    
    return render(request, 'generator/edit.html', context)

# Функция для установки режима
@csrf_exempt
def set_generation_mode(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            request.session['is_template_mode'] = data.get('mode') == 'template'
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error'}, status=405)


def generate_pdf(request):
    """
    Роутер для генерации PDF. Определяет тип генерации на основе флага в сессии.
    """
    if 'processed_data' not in request.session:
        return redirect('upload_file')
    
    # Выбираем обработчик в зависимости от режима
    if request.session.get('is_template_mode', False):
        return generate_templates(request)  # Режим генерации шаблонов
    else:
        return generate_bulk_labels(request)  # Режим массовой печати
    

def generate_templates_direct(request):
    """Генерация шаблонов напрямую со страницы редактирования"""
    if request.method == 'POST':
        # Получаем данные из сессии
        if not all(key in request.session for key in ['excel_path', 'header_row', 'selected_columns', 'column_mapping']):
            return redirect('upload_file')
        
        # Чтение Excel-файла
        df = pd.read_excel(request.session['excel_path'], header=request.session['header_row'])
        raw_data = df[request.session['selected_columns']].to_dict('records')
        
        # Получаем название колонки с размером
        size_column = request.session['column_mapping'].get('size')

        # Создаем формсет
        EditFormSet = formset_factory(EditDataForm, extra=0)
        formset = EditFormSet(request.POST)
        
        if formset.is_valid():
            grouped = {}
            for i, item in enumerate(raw_data):
                try:
                    form_data = formset[i].cleaned_data
                except IndexError:
                    form_data = {'color': '', 'size': '', 'quantity': 1}
                
                # Нормализация данных
                article = str(item.get(request.session['column_mapping']['article'], '')).strip().lower()
                barcode = str(item.get(request.session['column_mapping']['barcode'], '')).strip().lower()
                color = form_data.get('color', str(item.get('Цвет', '')).strip().lower())
                size = form_data.get('size', str(item.get('Размер', '')).strip().lower())
                size = form_data.get('size', str(item.get(size_column, '')).strip().lower()) if size_column else ''

                key = f"{article}|{barcode}|{color}|{size}"
                if key not in grouped:
                    grouped[key] = {
                        'data': item.copy(),
                        'quantity': 1  # Для шаблонов всегда 1
                    }
                    grouped[key]['data']['Цвет'] = color
                    if size_column:
                        grouped[key]['data']['Размер'] = size

            # Сохраняем данные в сессии
            request.session['processed_data'] = list(grouped.values())
            request.session['is_template_mode'] = True
            
            # Вызываем стандартную функцию генерации шаблонов
            return generate_templates(request)
    
    return redirect('edit_data')


def generate_templates(request):
    """
    Генерация отдельных PDF-файлов для каждого уникального товара.
    Каждый файл сохраняется в папке шаблонов.
    """
    processed_data = request.session['processed_data']
    legal_data = get_legal_entities()
    
    # Создаем папку для шаблонов, если она не существует
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    
    created = 0  # Счетчик созданных файлов
    skipped = 0  # Счетчик пропущенных файлов (уже существующих)

    # Регистрируем шрифт Arial
    pdfmetrics.registerFont(TTFont('Arial', 'arial.ttf'))
    styles = getSampleStyleSheet()

    # =======================================================
    # НАСТРОЙКА СТИЛЕЙ ТЕКСТА (одинаковые для всех режимов)
    # =======================================================
    
    # Стиль для названия компании
    company_style = styles["Normal"].clone('CompanyStyle')
    company_style.fontName = "Arial"
    company_style.fontSize = COMPANY_FONT_SIZE
    company_style.alignment = 1  # Выравнивание по центру
    company_style.leading = COMPANY_FONT_SIZE * 1.2  # Межстрочный интервал
    company_style.spaceBefore = 1  # Отступ сверху
    company_style.spaceAfter = 1   # Отступ снизу

    # Стиль для названия товара
    product_style = styles["Normal"].clone('ProductStyle')
    product_style.fontName = "Arial"
    product_style.fontSize = PRODUCT_FONT_SIZE
    product_style.alignment = 1
    product_style.leading = PRODUCT_FONT_SIZE * 1.3
    product_style.splitLongWords = True  # Разрешаем перенос длинных слов
    product_style.wordWrap = 'CJK'       # Алгоритм переноса для кириллицы
    product_style.leftIndent = PRODUCT_SIDE_PADDING  # Левый отступ
    product_style.rightIndent = PRODUCT_SIDE_PADDING  # Правый отступ

    # Стиль для артикула
    article_style = styles["Normal"].clone('ArticleStyle')
    article_style.fontName = "Arial"
    article_style.fontSize = ARTICLE_FONT_SIZE
    article_style.alignment = 1
    article_style.leading = ARTICLE_FONT_SIZE * 1.1
    article_style.spaceBefore = 0.5 * mm  # Отступ сверху
    article_style.spaceAfter = 0.5 * mm   # Отступ снизу

    # Стиль для дополнительной информации (цвет/размер)
    color_style = styles["Normal"].clone('ColorStyle')
    color_style.fontName = "Arial"
    color_style.fontSize = EXTRA_FONT_SIZE
    color_style.alignment = 1
    color_style.leading = EXTRA_FONT_SIZE * 1.1
    color_style.spaceBefore = 1 * mm

    # Обработка каждого товара
    for product in processed_data:
        data = product['data']
        
        # Формируем имя файла на основе штрих-кода и названия товара
        barcode = str(data.get('Баркод', 'N/A')).strip()
        product_name = str(data.get('Наименование', 'без_названия'))[:60]  # Обрезаем длинные названия
        clean_name = product_name.replace(' ', ' ').replace('/', '-')  # Заменяем спецсимволы
        filename = f"{barcode} {clean_name}.pdf"
        filepath = os.path.join(TEMPLATES_DIR, filename)
        
        # Пропускаем существующие файлы
        if os.path.exists(filepath):
            skipped += 1
            continue
            
        try:
            # Создаем PDF-документ
            response = HttpResponse(content_type='application/pdf')
            p = canvas.Canvas(response, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
            
            current_y = PAGE_HEIGHT - MARGIN  # Стартовая позиция по Y
            
            # Отрисовка штрих-кода (если он есть)
            if barcode != 'N/A':
                # Генерация штрих-кода
                barcode_img = code128.Code128(
                    barcode,
                    barHeight=BARCODE_HEIGHT,
                    barWidth=BARCODE_BAR_WIDTH
                )
                # Центрирование штрих-кода
                barcode_x = (PAGE_WIDTH - barcode_img.width) / 2
                barcode_img.drawOn(p, barcode_x, current_y - BARCODE_TOP_MARGIN)
                
                # Текст под штрих-кодом
                p.setFont("Arial", BARCODE_TEXT_SIZE)
                text_width = p.stringWidth(barcode, "Arial", BARCODE_TEXT_SIZE)
                text_x = (PAGE_WIDTH - text_width) / 2
                p.drawString(text_x, current_y - BARCODE_TOP_MARGIN - BARCODE_TEXT_OFFSET, barcode)
                
                # Смещаем позицию Y вниз после штрих-кода
                current_y -= AFTER_BARCODE_SPACE

            # Список элементов для отображения (текст + стиль)
            elements = [
                (legal_data['current'], company_style),  # Динамическое название
                (data.get('Наименование', 'Без названия'), product_style),
                (f"Артикул: {data.get('Артикул', 'N/A')}", article_style)
            ]
            
            # Добавляем размер, если он указан
            if 'Размер' in data and data['Размер']:
                elements.append((f"Размер: {data['Размер']}", color_style))

            # Добавляем цвет, если он указан
            if data.get('Цвет'):
                elements.append((f"Цвет: {data['Цвет']}", color_style))
            
            # Отрисовка всех текстовых элементов
            for text, style in elements:
                para = Paragraph(text, style)
                w, h = para.wrap(PAGE_WIDTH, PAGE_HEIGHT)  # Определение размера элемента
                x = (PAGE_WIDTH - w) / 2  # Центрирование по горизонтали
                para.drawOn(p, x, current_y - h)  # Отрисовка параграфа
                
                # Смещаем позицию Y с учетом отступа стиля
                current_y -= h + style.spaceAfter

            # Завершаем страницу
            p.showPage()
            p.save()
            
            # Сохраняем файл на диск
            with open(filepath, 'wb') as f:
                f.write(response.content)
            created += 1
            
        except Exception as e:
            logger.error(f"Ошибка генерации шаблона {filename}: {str(e)}")
    
    # Возвращаем отчет с кнопкой возврата
    return render(request, 'generator/template_report.html', {
        'created': created,
        'skipped': skipped,
        'templates_dir': TEMPLATES_DIR
    })

def generate_bulk_labels(request):
    """
    Генерация единого PDF-файла с множеством этикеток для массовой печати.
    """
    processed_data = request.session['processed_data']
    legal_data = get_legal_entities()

    # =====================================================
    # СТАТИСТИКА И ЛОГИРОВАНИЕ
    # =====================================================
    total_labels = sum(item['quantity'] for item in processed_data)
    unique_products = len(processed_data)
    zakazes = total_labels // 2  # Каждому заказу соответствует 2 этикетки
    
    # Логирование статистики
    logger.info(f"Сгенерировано этикеток: {total_labels}")
    logger.info(f"Уникальных товаров: {unique_products}")
    logger.info(f"Заказов: {zakazes}")
    
    # Вывод в консоль для быстрого просмотра
    print(f"\n=== ОТЧЕТ ===")
    print(f"Заказов: {zakazes}")
    print(f"Уникальных товаров: {unique_products}")
    print(f"Всего этикеток: {total_labels}")
    print("==============\n")
    
    # Подготовка PDF-документа для скачивания
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="labels.pdf"'
    
    # Регистрируем шрифт Arial
    pdfmetrics.registerFont(TTFont('Arial', 'arial.ttf'))
    p = canvas.Canvas(response, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))

    # Стили текста (используем те же, что и для шаблонов)
    styles = getSampleStyleSheet()
    
    # Стиль для названия компании
    company_style = styles["Normal"].clone('CompanyStyle')
    company_style.fontName = "Arial"
    company_style.fontSize = COMPANY_FONT_SIZE
    company_style.alignment = 1
    company_style.leading = COMPANY_FONT_SIZE * 1.2
    company_style.spaceBefore = 1
    company_style.spaceAfter = 1

    # Стиль для названия товара
    product_style = styles["Normal"].clone('ProductStyle')
    product_style.fontName = "Arial"
    product_style.fontSize = PRODUCT_FONT_SIZE
    product_style.alignment = 1
    product_style.leading = PRODUCT_FONT_SIZE * 1.3
    product_style.splitLongWords = True
    product_style.wordWrap = 'CJK'
    product_style.leftIndent = PRODUCT_SIDE_PADDING
    product_style.rightIndent = PRODUCT_SIDE_PADDING

    # Стиль для артикула
    article_style = styles["Normal"].clone('ArticleStyle')
    article_style.fontName = "Arial"
    article_style.fontSize = ARTICLE_FONT_SIZE
    article_style.alignment = 1
    article_style.leading = ARTICLE_FONT_SIZE * 1.1
    article_style.spaceBefore = 0.5 * mm
    article_style.spaceAfter = 0.5 * mm

    # Стиль для дополнительной информации (цвет/размер)
    color_style = styles["Normal"].clone('ColorStyle')
    color_style.fontName = "Arial"
    color_style.fontSize = EXTRA_FONT_SIZE
    color_style.alignment = 1
    color_style.leading = EXTRA_FONT_SIZE * 1.1
    color_style.spaceBefore = 1 * mm

    # Обработка каждого товара
    for product in processed_data:
        data = product['data']
        quantity = product['quantity']  # Количество этикеток для этого товара
        
        # Генерация указанного количества этикеток
        for _ in range(quantity):
            current_y = PAGE_HEIGHT - MARGIN  # Стартовая позиция по Y
            
            # Отрисовка штрих-кода (если он есть)
            barcode_value = str(data.get('Баркод', 'N/A')).strip()
            if barcode_value != 'N/A':
                # Генерация штрих-кода
                barcode = code128.Code128(
                    barcode_value,
                    barHeight=BARCODE_HEIGHT,
                    barWidth=BARCODE_BAR_WIDTH
                )
                # Центрирование штрих-кода
                barcode_x = (PAGE_WIDTH - barcode.width) / 2
                barcode.drawOn(p, barcode_x, current_y - BARCODE_TOP_MARGIN)
                
                # Текст под штрих-кодом
                p.setFont("Arial", BARCODE_TEXT_SIZE)
                text_width = p.stringWidth(barcode_value, "Arial", BARCODE_TEXT_SIZE)
                text_x = (PAGE_WIDTH - text_width) / 2
                p.drawString(text_x, current_y - BARCODE_TOP_MARGIN - BARCODE_TEXT_OFFSET, barcode_value)
                
                # Смещаем позицию Y вниз после штрих-кода
                current_y -= AFTER_BARCODE_SPACE

            # Список элементов для отображения (текст + стиль)
            elements = [
                (legal_data['current'], company_style),  # Динамическое название
                (data.get('Наименование', 'Без названия'), product_style),
                (f"Артикул: {data.get('Артикул', 'N/A')}", article_style)
            ]

            # Добавляем размер, если он есть и не пустой
            if 'Размер' in data and data['Размер']:
                elements.append((f"Размер: {data['Размер']}", color_style))
                        
            # Добавляем цвет, если он есть и не пустой
            if data.get('Цвет'):
                elements.append((f"Цвет: {data['Цвет']}", color_style))

            # Отрисовка всех текстовых элементов
            for text, style in elements:
                para = Paragraph(text, style)
                w, h = para.wrap(PAGE_WIDTH, PAGE_HEIGHT)  # Определение размера элемента
                x = (PAGE_WIDTH - w) / 2  # Центрирование по горизонтали
                para.drawOn(p, x, current_y - h)  # Отрисовка параграфа
                
                # Смещаем позицию Y с учетом отступа стиля
                current_y -= h + style.spaceAfter

            # Завершаем страницу
            p.showPage()
    
    # Сохраняем PDF-документ
    p.save()
    return response