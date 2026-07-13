const LANGUAGE_OPTIONS = Object.freeze([
    Object.freeze({ code: 'en', label: 'Inglês' }),
    Object.freeze({ code: 'pt-BR', label: 'Português (Brasil)' }),
    Object.freeze({ code: 'es', label: 'Espanhol' }),
    Object.freeze({ code: 'fr', label: 'Francês' }),
    Object.freeze({ code: 'de', label: 'Alemão' }),
    Object.freeze({ code: 'it', label: 'Italiano' }),
    Object.freeze({ code: 'ja', label: 'Japonês' }),
    Object.freeze({ code: 'ko', label: 'Coreano' }),
    Object.freeze({ code: 'zh-CN', label: 'Chinês (Simplificado)' }),
    Object.freeze({ code: 'zh-TW', label: 'Chinês (Tradicional)' }),
    Object.freeze({ code: 'ru', label: 'Russo' }),
    Object.freeze({ code: 'nl', label: 'Holandês' }),
    Object.freeze({ code: 'pl', label: 'Polonês' }),
    Object.freeze({ code: 'tr', label: 'Turco' })
]);

const LANGUAGE_CODES = new Set(LANGUAGE_OPTIONS.map(language => language.code));

function languageOptions() {
    return LANGUAGE_OPTIONS.map(language => ({ ...language }));
}

module.exports = { LANGUAGE_CODES, LANGUAGE_OPTIONS, languageOptions };
