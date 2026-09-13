// Bindings from wrangler.jsonc show up on event.platform.env at request time.
declare global {
	namespace App {
		interface Platform {
			env: {
				PERSONAS: KVNamespace;
				LIMITER: DurableObjectNamespace;
				OPENAI_API_KEY?: string;
				OPENAI_BASE_URL?: string;
				OPENAI_MODEL?: string;
				ELEVENLABS_API_KEY?: string;
				ECHO_DAILY_MESSAGE_CAP?: string;
				ECHO_IP_BURST?: string;
				ECHO_UNLOCK_BURST?: string;
				ECHO_SHARED_VOICE_CAP?: string;
				ECHO_ADMIN_TOKEN?: string;
				ECHO_TOTP_GRANTS?: string;
			};
			context: ExecutionContext;
		}
	}

	interface KVNamespace {
		get(key: string, type?: 'text'): Promise<string | null>;
		get<T>(key: string, type: 'json'): Promise<T | null>;
		put(key: string, value: string, options?: { expirationTtl?: number }): Promise<void>;
		delete(key: string): Promise<void>;
	}

	interface DurableObjectNamespace {
		idFromName(name: string): DurableObjectId;
		get(id: DurableObjectId): { fetch(input: string | Request): Promise<Response> };
	}

	interface DurableObjectId {
		toString(): string;
	}

	interface ExecutionContext {
		waitUntil(promise: Promise<unknown>): void;
	}
}

export {};
