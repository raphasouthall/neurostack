import { writable } from 'svelte/store';
import { onAuthStateChanged, onIdTokenChanged, signOut, type User } from 'firebase/auth';
import { auth } from '$lib/firebase';

interface AuthState {
	user: User | null;
	loading: boolean;
	idToken: string | null;
}

export const authStore = writable<AuthState>({
	user: null,
	loading: true,
	idToken: null
});

if (typeof window !== 'undefined') {
	onAuthStateChanged(auth, async (user) => {
		if (user) {
			const token = await user.getIdToken();
			authStore.set({ user, loading: false, idToken: token });
		} else {
			authStore.set({ user: null, loading: false, idToken: null });
		}
	});

	onIdTokenChanged(auth, async (user) => {
		if (user) {
			const token = await user.getIdToken();
			authStore.update((state) => ({ ...state, idToken: token }));
		}
	});
}

export async function getIdToken(): Promise<string | null> {
	return (await auth.currentUser?.getIdToken(true)) ?? null;
}

export async function logout(): Promise<void> {
	await signOut(auth);
}
