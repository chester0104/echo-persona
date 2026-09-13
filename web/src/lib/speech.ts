// Browser speech fallback for when ElevenLabs is unavailable or the plan lapses.
export type BrowserVoiceOptions = {
	pitch?: number;
	rate?: number;
	preferFemale?: boolean;
};

const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2190}-\u{21FF}\u{2B00}-\u{2BFF}\uFE0F]/gu;

export function strip(text: string): string {
	return text
		.split('\n')
		.map((line) => line.replace(EMOJI, '').replace(/[ \t]+/g, ' ').trim())
		.filter(Boolean)
		.map((line) => (/[.!?,:;]$/.test(line) ? line : `${line}.`))
		.join(' ');
}

export function browserSpeechAvailable(): boolean {
	return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

function pickVoice(preferFemale: boolean): SpeechSynthesisVoice | undefined {
	const voices = window.speechSynthesis.getVoices();
	if (!voices.length) return undefined;
	const english = voices.filter((voice) => voice.lang.toLowerCase().startsWith('en'));
	const pool = english.length ? english : voices;
	if (preferFemale) {
		const hinted = pool.find((voice) => /female|zira|aria|samantha|jenny|libby/i.test(voice.name));
		if (hinted) return hinted;
	}
	return pool[0];
}

export function speakInBrowser(text: string, options: BrowserVoiceOptions = {}): Promise<void> {
	return new Promise((resolve) => {
		if (!browserSpeechAvailable()) return resolve();
		const clean = strip(text);
		if (!clean) return resolve();
		window.speechSynthesis.cancel();
		const utterance = new SpeechSynthesisUtterance(clean);
		const voice = pickVoice(options.preferFemale ?? false);
		if (voice) utterance.voice = voice;
		utterance.pitch = options.pitch ?? 1.05;
		utterance.rate = options.rate ?? 1.02;
		utterance.onend = () => resolve();
		utterance.onerror = () => resolve();
		window.speechSynthesis.speak(utterance);
	});
}

export function cancelBrowserSpeech(): void {
	if (browserSpeechAvailable()) window.speechSynthesis.cancel();
}
