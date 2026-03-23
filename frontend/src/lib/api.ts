import { getIdToken } from '$lib/stores/auth';

const baseUrl = import.meta.env.VITE_API_URL || '';

export async function apiFetch(path: string, options?: RequestInit): Promise<Response> {
	const token = await getIdToken();
	const headers = new Headers(options?.headers);

	if (token) {
		headers.set('Authorization', `Bearer ${token}`);
	}

	if (!headers.has('Content-Type') && options?.body) {
		headers.set('Content-Type', 'application/json');
	}

	return fetch(`${baseUrl}${path}`, {
		...options,
		headers
	});
}
