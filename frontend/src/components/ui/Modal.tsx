import type { PropsWithChildren } from "react";

export default function Modal({ children }: PropsWithChildren) {
  return <div className="modal">{children}</div>;
}
