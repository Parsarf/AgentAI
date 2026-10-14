import { configure } from '@testing-library/react';

// The default 1 s wait for "something shows up" fails when the machine is busy (a build, a deploy, other apps) even though the UI is fine.
configure({ asyncUtilTimeout: 5000 });
