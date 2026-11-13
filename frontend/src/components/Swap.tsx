import type { ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { EASE, useReducedMotion } from "@/lib/motion";

/** Cross-fades between panel states (empty, scanning, results). With reduced
 *  motion the content is swapped directly. */
export function Swap({ id, children }: { id: string; children: ReactNode }) {
  const reduced = useReducedMotion();
  if (reduced) return <>{children}</>;
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={id}
        className="panel-state"
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.16, ease: EASE }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
