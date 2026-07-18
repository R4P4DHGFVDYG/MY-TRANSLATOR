const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function inlineScripts(fileName) {
    const html = fs.readFileSync(path.join(__dirname, fileName), 'utf8');
    return [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)]
        .map(match => match[1]);
}

for (const fileName of ['index.html', 'overlay_editor.html', 'toast.html']) {
    test(`${fileName} contains syntactically valid inline scripts`, () => {
        const scripts = inlineScripts(fileName);
        assert.ok(scripts.length > 0);
        scripts.forEach((source, index) => {
            assert.doesNotThrow(
                () => new vm.Script(source, { filename: `${fileName}:inline-${index + 1}` })
            );
        });
    });
}

test('translation overlay keeps capture fallback and responsive overflow guards', () => {
    const indexHtml = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
    const mainSource = fs.readFileSync(path.join(__dirname, 'main.js'), 'utf8');
    const toastHtml = fs.readFileSync(path.join(__dirname, 'toast.html'), 'utf8');
    const showToastSource = mainSource.match(/function showToast[\s\S]*?function redisplayToastAfterLayoutChange/)?.[0] || '';
    assert.match(indexHtml, /id="overlayAreaButton"/);
    assert.doesNotMatch(indexHtml, /id="position"/);
    assert.doesNotMatch(indexHtml, /getElementById\(['"]position['"]\)/);
    assert.doesNotMatch(indexHtml, /auto8bit|Automático — 8 bits/);
    assert.match(indexHtml, /getOverlayAreaState\(\)/);
    assert.match(indexHtml, /Usando a área de captura como padrão/);
    assert.match(toastHtml, /max-height:\s*100%/);
    assert.match(toastHtml, /overflow-wrap:\s*anywhere/);
    assert.match(toastHtml, /createLatestFrameScheduler/);
    assert.match(toastHtml, /class="toast-shell passive-overlay"/);
    assert.match(showToastSource, /focusable:\s*false/);
    assert.match(showToastSource, /setIgnoreMouseEvents\(true\)/);
    assert.equal((showToastSource.match(/setIgnoreMouseEvents/g) || []).length, 1);
    assert.doesNotMatch(showToastSource, /forward\s*:\s*true/);
    assert.match(showToastSource, /if \(!currentToast\.isVisible\(\)\)\s*{\s*showOverlay\(currentToast, true\)/);
});
