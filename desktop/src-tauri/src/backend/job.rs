//! Windows: the sidecar in a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. The app holds
//! the only handle to the job, so when the app ends in any way the sidecar ends too; closing
//! the handle early would kill the sidecar at once.

use std::ffi::c_void;
use std::io;

/// The three system calls, so that their order and the handle's lifetime are tested on Linux.
pub trait JobApi {
    type Job;
    fn create(&self) -> io::Result<Self::Job>;
    fn kill_on_close(&self, job: &Self::Job) -> io::Result<()>;
    fn assign(&self, job: &Self::Job, process: *mut c_void) -> io::Result<()>;
}

/// A job that ends `process` when the returned value is dropped.
pub fn contain<A: JobApi>(api: &A, process: *mut c_void) -> io::Result<A::Job> {
    let job = api.create()?;
    api.kill_on_close(&job)?;
    api.assign(&job, process)?;
    Ok(job)
}

#[cfg(windows)]
pub use system::{Job, System};

#[cfg(windows)]
mod system {
    use std::ffi::c_void;
    use std::io;

    use windows::Win32::Foundation::{CloseHandle, HANDLE};
    use windows::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation,
        SetInformationJobObject,
    };
    use windows::core::PCWSTR;

    use super::JobApi;

    pub struct Job(HANDLE);

    // SAFETY: a job handle may be used and closed from any thread.
    unsafe impl Send for Job {}
    // SAFETY: as above; the handle is only read.
    unsafe impl Sync for Job {}

    impl Drop for Job {
        fn drop(&mut self) {
            // SAFETY: the handle came from CreateJobObjectW and is closed once.
            unsafe {
                let _ = CloseHandle(self.0);
            }
        }
    }

    pub struct System;

    impl JobApi for System {
        type Job = Job;

        fn create(&self) -> io::Result<Job> {
            // SAFETY: no attributes and no name: an anonymous job with default security.
            unsafe { CreateJobObjectW(None, PCWSTR::null()) }
                .map(Job)
                .map_err(io::Error::other)
        }

        fn kill_on_close(&self, job: &Job) -> io::Result<()> {
            let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            // SAFETY: the pointer and the size are those of `info`, which outlives the call.
            unsafe {
                SetInformationJobObject(
                    job.0,
                    JobObjectExtendedLimitInformation,
                    (&raw const info).cast(),
                    size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                )
            }
            .map_err(io::Error::other)
        }

        fn assign(&self, job: &Job, process: *mut c_void) -> io::Result<()> {
            // SAFETY: `process` is the live child's handle, owned by its `Child`.
            unsafe { AssignProcessToJobObject(job.0, HANDLE(process)) }.map_err(io::Error::other)
        }
    }
}

#[cfg(test)]
mod tests {
    use std::cell::RefCell;
    use std::rc::Rc;

    use super::*;

    type Calls = Rc<RefCell<Vec<String>>>;

    struct Fake {
        calls: Calls,
        fail: Option<&'static str>,
    }

    struct FakeJob(Calls);

    impl Drop for FakeJob {
        fn drop(&mut self) {
            self.0.borrow_mut().push("close".to_owned());
        }
    }

    impl Fake {
        fn call(&self, name: &str) -> io::Result<()> {
            self.calls.borrow_mut().push(name.to_owned());
            match self.fail {
                Some(failing) if failing == name => Err(io::Error::other(name.to_owned())),
                _ => Ok(()),
            }
        }
    }

    impl JobApi for Fake {
        type Job = FakeJob;
        fn create(&self) -> io::Result<FakeJob> {
            self.call("create").map(|()| FakeJob(self.calls.clone()))
        }
        fn kill_on_close(&self, _job: &FakeJob) -> io::Result<()> {
            self.call("kill_on_close")
        }
        fn assign(&self, _job: &FakeJob, process: *mut c_void) -> io::Result<()> {
            self.call(&format!("assign {}", process as usize))
        }
    }

    fn calls(fake: &Fake) -> Vec<String> {
        fake.calls.borrow().clone()
    }

    #[test]
    fn the_sidecar_is_assigned_to_a_kill_on_close_job_that_stays_open() {
        let fake = Fake {
            calls: Calls::default(),
            fail: None,
        };
        let job = contain(&fake, 42 as *mut c_void).unwrap();
        assert_eq!(calls(&fake), ["create", "kill_on_close", "assign 42"]);
        drop(job);
        assert_eq!(calls(&fake).last().unwrap(), "close");
    }

    #[test]
    fn a_job_without_the_kill_limit_is_not_used() {
        let fake = Fake {
            calls: Calls::default(),
            fail: Some("kill_on_close"),
        };
        assert!(contain(&fake, 42 as *mut c_void).is_err());
        assert_eq!(calls(&fake), ["create", "kill_on_close", "close"]);
    }
}
