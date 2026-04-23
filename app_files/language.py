import json
from pathlib import Path
from flask import request, session

class LanguageManager:
    def __init__(self, app=None):
        self.app = app
        self.locales_dir = Path(__file__).parent.parent / 'locales'
        self.default_lang = 'en'
        self.supported_langs = ['en', 'ko', 'ja', 'zh']
        self.translations = {}
        
        # Load all language files
        for lang in self.supported_langs:
            self.load_language(lang)
        
        if app:
            self.init_app(app)
    
    def load_language(self, lang_code):
        """Load language file into memory"""
        lang_file = self.locales_dir / f'{lang_code}.json'
        if lang_file.exists():
            try:
                with open(lang_file, 'r', encoding='utf-8') as f:
                    self.translations[lang_code] = json.load(f)
            except Exception as e:
                print(f"Error loading language {lang_code}: {e}")
                self.translations[lang_code] = {}
        else:
            self.translations[lang_code] = {}
    
    def init_app(self, app):
        """Initialize Flask app with language support"""
        
        @app.before_request
        def before_request():
            # Get language from cookie, session, or request header
            lang = request.cookies.get('language')
            if not lang or lang not in self.supported_langs:
                # Try to get from Accept-Language header
                accept_lang = request.accept_languages.best_match(self.supported_langs)
                lang = accept_lang if accept_lang else self.default_lang
            session['language'] = lang
        
        # Make language function available in templates
        @app.context_processor
        def inject_language():
            return {
                '_': self.get_translation,
                'current_lang': lambda: session.get('language', self.default_lang),
                'supported_langs': self.supported_langs
            }
    
    def get_translation(self, key, lang=None):
        """Get translation for a key"""
        if not lang:
            lang = session.get('language', self.default_lang)
        
        # Try to get from requested language
        if lang in self.translations and key in self.translations[lang]:
            return self.translations[lang][key]
        
        # Fallback to default language
        if self.default_lang in self.translations and key in self.translations[self.default_lang]:
            return self.translations[self.default_lang][key]
        
        # Return key if translation not found
        return key
    
    def get_all_translations(self, lang):
        """Get all translations for a language"""
        return self.translations.get(lang, {})

# Create global instance
lang_manager = LanguageManager()