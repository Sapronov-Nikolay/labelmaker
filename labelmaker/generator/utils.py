import json
import os
from pathlib import Path
from django.conf import settings

DEFAULT_ENTITY = 'ООО "МЕДИЦИНСКИЕ РАСХОДНИКИ"'
SETTINGS_FILE = Path(settings.MEDIA_ROOT) / 'legal_entities.json'

def save_legal_entities(data):
    """Сохраняем данные в файл"""
    try:
        os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Файл сохранён: {SETTINGS_FILE}")
        return True
    except Exception as e:
        print(f"ОШИБКА сохранения: {e}")
        return False

def load_legal_entities():
    """Загружаем данные из файла"""
    if not SETTINGS_FILE.exists():
        default_data = {
            'current': DEFAULT_ENTITY,
            'entities': [DEFAULT_ENTITY]
        }
        save_legal_entities(default_data)
        return default_data
    
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"ОШИБКА загрузки: {e}")
        return {
            'current': DEFAULT_ENTITY,
            'entities': [DEFAULT_ENTITY]
        }

def get_legal_entities():
    """Получаем текущее юрлицо и список всех"""
    data = load_legal_entities()
    return {
        'current': data['current'],
        'all': data['entities']
    }

def update_legal_entity(new_entity, add_to_list=False):
    """Обновляем текущее юрлицо"""
    data = load_legal_entities()
    data['current'] = new_entity

    if add_to_list and new_entity not in data['entities']:
        data['entities'].append(new_entity)

    save_legal_entities(data)

def remove_legal_entity(entity_to_remove):
    """Удаляем юрлицо из списка"""
    data = load_legal_entities()
    
    if entity_to_remove in data['entities']:
        data['entities'].remove(entity_to_remove)
        
        # Если удаляем текущее, сбрасываем на значение по умолчанию
        if data['current'] == entity_to_remove:
            data['current'] = DEFAULT_ENTITY
        
        save_legal_entities(data)