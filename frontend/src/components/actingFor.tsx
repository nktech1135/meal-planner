import { createContext, useContext } from "react";

/**
 * Whose foods and recipes the pickers show. Set while adding to a plan someone shared with you: the
 * item has to be something the plan's owner can see, so searches run as them (the shared database plus
 * their own foods and recipes; your private ones aren't offered). Null: your own, as usual.
 */
export type ActingFor = { id: number; name: string } | null;

const ActingForContext = createContext<ActingFor>(null);

export const ActingForProvider = ActingForContext.Provider;

export function useActingFor(): ActingFor {
  return useContext(ActingForContext);
}
