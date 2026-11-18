/**
 * The sign-in form's state.
 *
 * Kept out of `actions.ts` because a `"use server"` module may only export async
 * functions: a type or a constant alongside the actions breaks the build.
 */

export type LoginState = {
  error: string | null;
  /** The API asked for a one-time code: show the authenticator step. */
  needsTotp: boolean;
  /** A temporary password has to be changed before anything else. */
  mustChangePassword: boolean;
  username: string;
};

export const INITIAL_LOGIN_STATE: LoginState = {
  error: null,
  needsTotp: false,
  mustChangePassword: false,
  username: "",
};
