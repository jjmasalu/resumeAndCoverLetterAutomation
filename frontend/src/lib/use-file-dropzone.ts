"use client";

import { useCallback, useRef, useState } from "react";
import type { DragEvent } from "react";

function hasFiles(event: { dataTransfer?: DataTransfer | null }) {
  const types = event.dataTransfer?.types;
  return types ? Array.from(types).includes("Files") : false;
}

export function useFileDropzone(onFiles: (files: File[]) => void) {
  const [isDragOver, setIsDragOver] = useState(false);
  const dragDepthRef = useRef(0);

  const handleDragEnter = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      dragDepthRef.current += 1;
      setIsDragOver(true);
    },
    []
  );

  const handleDragOver = useCallback((event: DragEvent<HTMLElement>) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    if (!isDragOver) {
      setIsDragOver(true);
    }
  }, [isDragOver]);

  const handleDragLeave = useCallback((event: DragEvent<HTMLElement>) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) {
      setIsDragOver(false);
    }
  }, []);

  const handleDrop = useCallback(
      (event: DragEvent<HTMLElement>) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      dragDepthRef.current = 0;
      setIsDragOver(false);
      const files = Array.from(event.dataTransfer.files || []);
      if (files.length > 0) {
        onFiles(files);
      }
    },
    [onFiles]
  );

  return {
    isDragOver,
    dropzoneProps: {
      onDragEnter: handleDragEnter,
      onDragOver: handleDragOver,
      onDragLeave: handleDragLeave,
      onDrop: handleDrop,
    },
  };
}
