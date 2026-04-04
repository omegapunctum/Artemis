export const DEFAULT_DISPLAY_MODE = 'points';

export function createCoursesState(courses = []) {
  return {
    courses: Array.isArray(courses) ? courses : [],
    selectedCourseId: null,
    selectedCourseStepIndex: 0
  };
}

export function getSelectedCourse(coursesState) {
  if (!coursesState?.selectedCourseId) return null;
  return (coursesState.courses || []).find((course) => String(course?.id) === String(coursesState.selectedCourseId)) || null;
}

export function selectCourse(coursesState, courseId) {
  coursesState.selectedCourseId = courseId ? String(courseId) : null;
  coursesState.selectedCourseStepIndex = 0;
}

export function moveCourseStep(coursesState, delta = 0) {
  const selectedCourse = getSelectedCourse(coursesState);
  const totalSteps = Array.isArray(selectedCourse?.steps) ? selectedCourse.steps.length : 0;
  if (!totalSteps) {
    coursesState.selectedCourseStepIndex = 0;
    return;
  }
  const nextValue = coursesState.selectedCourseStepIndex + Number(delta || 0);
  coursesState.selectedCourseStepIndex = Math.max(0, Math.min(totalSteps - 1, nextValue));
}

export function createLiveState(features = []) {
  return {
    isLiveMode: false,
    liveFeatures: Array.isArray(features) ? features : []
  };
}

export function aggregateFeaturesByDecade(features = []) {
  const buckets = {};
  (Array.isArray(features) ? features : []).forEach((feature) => {
    const props = feature?.properties || {};
    const year = parseYear(props?.date_start ?? props?.date_construction_end ?? props?.date_end);
    if (!Number.isFinite(year)) return;
    const decade = Math.floor(year / 10) * 10;
    const bucketKey = String(decade);
    buckets[bucketKey] = (buckets[bucketKey] || 0) + 1;
  });
  return buckets;
}

function parseYear(value) {
  if (value === null || value === undefined || value === '') return Number.NaN;
  const parsed = Number.parseInt(String(value), 10);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}
