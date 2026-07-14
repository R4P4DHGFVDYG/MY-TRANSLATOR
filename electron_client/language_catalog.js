const LANGUAGE_OPTIONS = Object.freeze([
    Object.freeze({ code: 'en', label: 'Inglês' }),
    Object.freeze({ code: 'pt-BR', label: 'Português (Brasil)' })
]);

const LANGUAGE_CODES = new Set(LANGUAGE_OPTIONS.map(language => language.code));

function languageOptions() {
    return LANGUAGE_OPTIONS.map(language => ({ ...language }));
}

module.exports = { LANGUAGE_CODES, LANGUAGE_OPTIONS, languageOptions };
