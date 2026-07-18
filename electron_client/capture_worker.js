'use strict';

(() => {
    const video = document.getElementById('captureVideo');
    const snapshots = new Map();
    const MAX_SNAPSHOTS = 4;
    const READY_TIMEOUT_MS = 8000;
    let stream = null;
    let nextSnapshotId = 0;

    function positiveInteger(value, fallback = 1) {
        const numeric = Number(value);
        return Number.isFinite(numeric) && numeric > 0
            ? Math.max(1, Math.round(numeric))
            : fallback;
    }

    function normalizedRectangle(value) {
        if (!value || typeof value !== 'object') {
            throw new TypeError('A capture rectangle is required.');
        }
        const x = Number(value.x);
        const y = Number(value.y);
        const width = Number(value.width);
        const height = Number(value.height);
        if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) {
            throw new TypeError('The capture rectangle is invalid.');
        }
        return { x, y, width, height };
    }

    function createCanvas(width, height) {
        if (typeof OffscreenCanvas === 'function') {
            return new OffscreenCanvas(width, height);
        }
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = height;
        return canvas;
    }

    function releaseCanvas(canvas) {
        if (canvas) {
            canvas.width = 1;
            canvas.height = 1;
        }
    }

    function releaseSnapshot(snapshotId) {
        const snapshot = snapshots.get(snapshotId);
        if (!snapshot) {
            return false;
        }
        snapshots.delete(snapshotId);
        releaseCanvas(snapshot.canvas);
        return true;
    }

    function clearSnapshots() {
        for (const snapshot of snapshots.values()) {
            releaseCanvas(snapshot.canvas);
        }
        snapshots.clear();
    }

    function stopStream() {
        clearSnapshots();
        if (stream) {
            for (const track of stream.getTracks()) {
                track.stop();
            }
        }
        stream = null;
        video.pause();
        video.srcObject = null;
    }

    function waitForVideo() {
        if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.videoWidth > 0) {
            return Promise.resolve();
        }
        return new Promise((resolve, reject) => {
            const timeoutId = setTimeout(() => {
                cleanup();
                reject(new Error('The screen capture stream did not become ready.'));
            }, READY_TIMEOUT_MS);
            const cleanup = () => {
                clearTimeout(timeoutId);
                video.removeEventListener('loadeddata', onReady);
                video.removeEventListener('error', onError);
            };
            const onReady = () => {
                cleanup();
                resolve();
            };
            const onError = () => {
                cleanup();
                reject(new Error('The screen capture stream could not be decoded.'));
            };
            video.addEventListener('loadeddata', onReady, { once: true });
            video.addEventListener('error', onError, { once: true });
        });
    }

    async function start(payload = {}) {
        stopStream();
        const maximumFrameRate = Math.min(15, positiveInteger(payload.maxFrameRate, 8));
        const nextStream = await navigator.mediaDevices.getDisplayMedia({
            audio: false,
            video: {
                frameRate: {
                    ideal: maximumFrameRate,
                    max: maximumFrameRate
                }
            }
        });
        stream = nextStream;
        const [videoTrack] = nextStream.getVideoTracks();
        if (!videoTrack) {
            stopStream();
            throw new Error('The selected display did not provide a video track.');
        }
        try {
            await videoTrack.applyConstraints({
                frameRate: { ideal: maximumFrameRate, max: maximumFrameRate }
            });
        } catch {
            // Some Windows capture drivers expose a fixed frame rate.
        }
        videoTrack.addEventListener('ended', () => {
            if (stream !== nextStream) {
                return;
            }
            stream = null;
            video.srcObject = null;
            clearSnapshots();
        }, { once: true });
        video.srcObject = stream;
        await video.play();
        await waitForVideo();
        return {
            width: video.videoWidth,
            height: video.videoHeight,
            frameRate: videoTrack.getSettings().frameRate || null
        };
    }

    function luminanceSignature(canvas, width, height) {
        const signatureCanvas = createCanvas(width, height);
        const context = signatureCanvas.getContext('2d', {
            alpha: false,
            willReadFrequently: true
        });
        if (!context) {
            releaseCanvas(signatureCanvas);
            throw new Error('The capture worker could not create a 2D context.');
        }
        context.imageSmoothingEnabled = true;
        context.imageSmoothingQuality = 'high';
        context.drawImage(canvas, 0, 0, width, height);
        const pixels = context.getImageData(0, 0, width, height).data;
        const signature = new Array(width * height);
        for (let pixel = 0; pixel < signature.length; pixel += 1) {
            const offset = pixel * 4;
            signature[pixel] = Math.round(
                (pixels[offset] * 77 + pixels[offset + 1] * 150 + pixels[offset + 2] * 29)
                / 256
            );
        }
        releaseCanvas(signatureCanvas);
        return signature;
    }

    async function capture(payload = {}) {
        if (!stream || video.videoWidth <= 0 || video.videoHeight <= 0) {
            throw new Error('The persistent screen capture stream is not active.');
        }
        const selection = normalizedRectangle(payload.selection);
        const displayBounds = normalizedRectangle(payload.displayBounds);
        const scaleX = video.videoWidth / displayBounds.width;
        const scaleY = video.videoHeight / displayBounds.height;
        const left = Math.max(0, Math.min(video.videoWidth, Math.round(selection.x * scaleX)));
        const top = Math.max(0, Math.min(video.videoHeight, Math.round(selection.y * scaleY)));
        const right = Math.max(
            left,
            Math.min(video.videoWidth, Math.round((selection.x + selection.width) * scaleX))
        );
        const bottom = Math.max(
            top,
            Math.min(video.videoHeight, Math.round((selection.y + selection.height) * scaleY))
        );
        const width = right - left;
        const height = bottom - top;
        const maxPixels = positiveInteger(payload.maxPixels, 12_000_000);
        if (width <= 0 || height <= 0 || width * height > maxPixels) {
            throw new Error('The selected capture area is invalid or too large.');
        }

        const captureStartedAt = performance.now();
        const canvas = createCanvas(width, height);
        const context = canvas.getContext('2d', { alpha: false });
        if (!context) {
            releaseCanvas(canvas);
            throw new Error('The capture worker could not create a snapshot.');
        }
        context.drawImage(video, left, top, width, height, 0, 0, width, height);
        const captureMs = performance.now() - captureStartedAt;

        const signatureStartedAt = performance.now();
        const signature = luminanceSignature(
            canvas,
            positiveInteger(payload.signatureWidth, 32),
            positiveInteger(payload.signatureHeight, 18)
        );
        const signatureMs = performance.now() - signatureStartedAt;
        const snapshotId = `snapshot-${Date.now()}-${++nextSnapshotId}`;
        snapshots.set(snapshotId, { canvas, width, height });
        while (snapshots.size > MAX_SNAPSHOTS) {
            releaseSnapshot(snapshots.keys().next().value);
        }

        return {
            snapshotId,
            width,
            height,
            signature,
            captureMs,
            signatureMs,
            cropPixels: width * height
        };
    }

    function canvasToBlob(canvas) {
        if (typeof canvas.convertToBlob === 'function') {
            return canvas.convertToBlob({ type: 'image/png' });
        }
        return new Promise((resolve, reject) => {
            canvas.toBlob(blob => {
                if (blob) {
                    resolve(blob);
                } else {
                    reject(new Error('The capture worker could not encode the snapshot.'));
                }
            }, 'image/png');
        });
    }

    function bytesToBase64(bytes) {
        const chunks = [];
        const chunkSize = 0x8000;
        for (let offset = 0; offset < bytes.length; offset += chunkSize) {
            chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + chunkSize)));
        }
        return btoa(chunks.join(''));
    }

    function digestToHex(buffer) {
        return Array.from(new Uint8Array(buffer), byte => byte.toString(16).padStart(2, '0')).join('');
    }

    async function encode(payload = {}) {
        const snapshotId = String(payload.snapshotId || '');
        const snapshot = snapshots.get(snapshotId);
        if (!snapshot) {
            throw new Error('The requested screen snapshot is no longer available.');
        }
        const encodeStartedAt = performance.now();
        try {
            const blob = await canvasToBlob(snapshot.canvas);
            const maxBytes = positiveInteger(payload.maxBytes, 12 * 1024 * 1024);
            if (blob.size > maxBytes) {
                throw new Error('The selected image is too large.');
            }
            const buffer = await blob.arrayBuffer();
            const bytes = new Uint8Array(buffer);
            const digest = await crypto.subtle.digest('SHA-256', buffer);
            return {
                dataUrl: `data:image/png;base64,${bytesToBase64(bytes)}`,
                digest: digestToHex(digest),
                encodedBytes: bytes.length,
                encodeMs: performance.now() - encodeStartedAt,
                width: snapshot.width,
                height: snapshot.height
            };
        } finally {
            releaseSnapshot(snapshotId);
        }
    }

    const methods = Object.freeze({
        capture,
        encode,
        release: payload => releaseSnapshot(String(payload?.snapshotId || '')),
        start,
        stop: () => {
            stopStream();
            return true;
        }
    });

    window.captureWorker = Object.freeze({
        invoke(method, payload) {
            const operation = methods[method];
            if (!operation) {
                throw new Error('Unsupported capture worker operation.');
            }
            return operation(payload);
        }
    });
})();
