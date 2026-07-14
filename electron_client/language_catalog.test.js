const test = require('node:test');
const assert = require('node:assert/strict');
const {
    LANGUAGE_CODES,
    LANGUAGE_OPTIONS,
    languageOptions
} = require('./language_catalog');

test('language catalog exposes unique source and target options', () => {
    assert.equal(LANGUAGE_OPTIONS.length, 2);
    assert.equal(LANGUAGE_CODES.size, LANGUAGE_OPTIONS.length);
    assert.deepEqual([...LANGUAGE_CODES], ['en', 'pt-BR']);
});

test('renderer receives copies instead of the internal catalog objects', () => {
    const options = languageOptions();

    assert.deepEqual(options, LANGUAGE_OPTIONS);
    assert.notEqual(options, LANGUAGE_OPTIONS);
    assert.notEqual(options[0], LANGUAGE_OPTIONS[0]);
});
