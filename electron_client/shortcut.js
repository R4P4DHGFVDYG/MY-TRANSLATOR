const MODIFIER_ORDER = ['Ctrl', 'Alt', 'Shift', 'Super'];
const MODIFIERS = new Set(MODIFIER_ORDER);
const MOUSE_SHORTCUTS = new Set(['MBUTTON', 'XBUTTON1', 'XBUTTON2']);
const NAMED_KEYS = new Set([
    'Space', 'Tab', 'Enter', 'Backspace', 'Delete', 'Insert',
    'Home', 'End', 'PageUp', 'PageDown', 'Up', 'Down', 'Left', 'Right'
]);

function normalizeKeyboardAccelerator(value) {
    if (typeof value !== 'string' || value.length > 80) {
        return null;
    }

    const tokens = value.split('+').map(token => token.trim()).filter(Boolean);
    if (tokens.length === 0) {
        return null;
    }

    const key = tokens.pop();
    const modifiers = new Set(tokens);
    if (modifiers.size !== tokens.length || [...modifiers].some(token => !MODIFIERS.has(token))) {
        return null;
    }

    const normalizedKey = /^[a-z]$/i.test(key)
        ? key.toUpperCase()
        : key;
    const isFunctionKey = /^F(?:[1-9]|1\d|2[0-4])$/.test(normalizedKey);
    const isRegularKey = /^[A-Z0-9]$/.test(normalizedKey) || NAMED_KEYS.has(normalizedKey);
    if (!isFunctionKey && !isRegularKey) {
        return null;
    }
    if (!isFunctionKey && modifiers.size === 0) {
        return null;
    }

    return [...MODIFIER_ORDER.filter(modifier => modifiers.has(modifier)), normalizedKey].join('+');
}

function normalizeCaptureShortcut(type, value) {
    if (type === 'keyboard') {
        const accelerator = normalizeKeyboardAccelerator(value);
        return accelerator ? { type, value: accelerator } : null;
    }
    if (type === 'mouse' && MOUSE_SHORTCUTS.has(value)) {
        return { type, value };
    }
    return null;
}

module.exports = {
    normalizeKeyboardAccelerator,
    normalizeCaptureShortcut
};
