import assert from 'node:assert/strict';
import {normalize} from '../normalize.js';
assert.equal(normalize(' A '),'a');
