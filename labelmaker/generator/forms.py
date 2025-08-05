from django import forms
from django.core.validators import FileExtensionValidator

class UploadForm(forms.Form):
    """Форма для выбора типа генерации этикеток"""
    bulk_file = forms.FileField(
        label='Для массовой печати этикеток',
        validators=[FileExtensionValidator(allowed_extensions=['xlsx'])],  # Разрешаем только Excel-файлы
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.xlsx'  # Подсказка браузеру для фильтрации файлов
        }),
        required=False,  # Поле необязательное
        help_text='Будет создан единый PDF-файл со всеми этикетками'
    )
    
    template_file = forms.FileField(
        label='Для генерации шаблонов',
        validators=[FileExtensionValidator(allowed_extensions=['xlsx'])],
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.xlsx'
        }),
        required=False,
        help_text='Создаст отдельные PDF-файлы для каждого товара'
    )
    def clean(self):
        cleaned_data = super().clean()
        bulk_file = cleaned_data.get('bulk_file')
        template_file = cleaned_data.get('template_file')
        
        if not bulk_file and not template_file:
            raise forms.ValidationError("Выберите один из вариантов загрузки")
        elif bulk_file and template_file:
            raise forms.ValidationError("Выберите только один вариант загрузки")
        
        return cleaned_data

class HeaderSelectForm(forms.Form): # для выбора строки заголовков.
    """Форма выбора строки заголовков"""
    header_row = forms.IntegerField(
        label='Номер строки с заголовками (начиная с 1)',
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )

class ColumnSelectForm(forms.Form): # для выбора колонок.
    """Форма выбора колонок"""
    def __init__(self, *args, **kwargs):
        columns = kwargs.pop('columns', [])
        super().__init__(*args, **kwargs)
        for col in columns:
            self.fields[col] = forms.BooleanField(
                label=col,
                required=False,
                widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
            )

class LabelSettingsForm(forms.Form):
    """Форма настройки соответствий колонок"""
    product_name_column = forms.ChoiceField(
        label='Колонка для названия товара',
        choices=[],  # Будет заполнено в __init__
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    barcode_column = forms.ChoiceField(
        label='Колонка для штрихкода',
        choices=[],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    article_column = forms.ChoiceField(
        label='Колонка для артикула',
        choices=[],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    size_column = forms.ChoiceField(
        label='Колонка для размера (необязательно)',
        required=False,
        choices=[('', '--- Не использовать ---')],  # Начальный пустой вариант
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        selected_columns = kwargs.pop('columns', [])
        super().__init__(*args, **kwargs)
        
        # Заполняем choices для основных полей (с вариантом "Выберите")
        for field_name in ['product_name_column', 'barcode_column', 'article_column']:
            self.fields[field_name].choices = [('', '--- Выберите ---')] + [(col, col) for col in selected_columns]
        
        # Для size_field добавляем варианты, сохраняя начальный "Не использовать"
        self.fields['size_column'].choices += [(col, col) for col in selected_columns]

class EditDataForm(forms.Form): # для редактирования данных перед генерацией PDF.
    """Форма редактирования данных"""
    color = forms.CharField(
        label='Цвет',
        required=False,
        widget=forms.TextInput(attrs={'class': 'table-input-1'})
    )
    size = forms.CharField(
        label='Размер',
        required=False,
        widget=forms.TextInput(attrs={'class': 'table-input-2'})
    )
    quantity = forms.IntegerField(
        label='Количество этикеток',
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'table-input-3'})
    )