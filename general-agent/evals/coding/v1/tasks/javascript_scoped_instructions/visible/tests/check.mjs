import assert from 'node:assert/strict';
import {label} from '../service/label.js';
assert.equal(label('a'),'nested:a');
