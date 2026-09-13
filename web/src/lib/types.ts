export type PersonaSummary = {
	id: string;
	name: string;
	tagline: string;
	quote?: string;
	accent: string;
	voiceReady: boolean;
	dataThrough?: string;
	pronoun?: string;
	builtIn: boolean;
	rhythm: {
		burst: number;
		medianChars: number;
		emojiPct: number;
		capsPct: number;
	};
};

export type PersonaPack = {
	schema: 'echo-persona/1';
	id: string;
	name: string;
	tagline?: string;
	quote?: string;
	accent?: string;
	styleCard: string;
	styleCardPrivate?: string;
	voiceId?: string;
	rhythm?: {
		burst?: number;
		medianChars?: number;
		emojiPct?: number;
		capsPct?: number;
	};
};

export type ChatTurn = {
	role: 'user' | 'assistant';
	content: string;
};

export type SpokenReply = {
	lines: string[];
	audio?: string;
	voice: 'cloned' | 'browser' | 'none';
	reason?: string;
};
