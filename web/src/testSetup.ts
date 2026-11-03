import { afterEach } from "vitest";
import { clearAnswers } from "./api";

// Each test serves its own answers.
afterEach(() => clearAnswers());
