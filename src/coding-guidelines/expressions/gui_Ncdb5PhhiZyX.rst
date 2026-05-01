.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Ensure all loops have a termination condition that is provably reachable
========================================================================

.. guideline:: Ensure all loops have a termination condition that is provably reachable
   :id: gui_Ncdb5PhhiZyX
   :category: required
   :status: draft
   :release: unknown
   :fls: fls_sf4qnd43z2wc
   :decidability: undecidable
   :scope: function
   :tags: safety

   All loops shall have a termination condition that can be demonstrated to be reachable
   under all valid execution paths.

   According to the Rust FLS, an ``infinite loop expression`` is a ``loop expression`` that
   continues to evaluate its ``loop body`` indefinitely. If the ``infinite loop expression``
   does not contain a ``break expression``, then the type is the ``never type``
   :cite:`gui_Ncdb5PhhiZyX:FLS-LOOPS`.

   Unbounded or potentially infinite loops are prohibited unless they serve as the main
   control loop with explicit external termination mechanisms.

   Loops must satisfy one of the following conditions:

   * Have a compile-time bounded iteration count
   * Have a loop variant (a value that monotonically decreases or increases toward the termination condition)
   * Be the designated main control loop with documented external termination (e.g., shutdown signal)

   .. rationale::
      :id: rat_o0WGQUuBxjpQ
      :status: draft

      Infinite or non-terminating loops pose significant risks in safety-critical systems:

      * **System availability**: A non-terminating loop can cause the system to become
        unresponsive, failing to perform its safety function.

      * **Watchdog timeout**: While hardware watchdogs can detect stuck systems,
        relying on watchdog reset as a termination mechanism indicates a design failure
        and may cause loss of critical state.

      * **Timing predictability**: Safety-critical systems often have strict timing
        requirements (deadlines). Loops without bounded execution time make worst-case
        execution time (WCET) analysis impossible.

      * **Resource exhaustion**: Loops that run longer than expected may exhaust stack
        space (through recursion), heap memory, or other resources.

      * **Certification requirements**: Standards such as DO-178C, ISO 26262, IEC 61508,
        and MISRA C:2012 require demonstration that software terminates correctly or
        handles non-termination safely :cite:`gui_Ncdb5PhhiZyX:DO-178C`
        :cite:`gui_Ncdb5PhhiZyX:ISO-26262` :cite:`gui_Ncdb5PhhiZyX:IEC-61508`
        :cite:`gui_Ncdb5PhhiZyX:MISRA-C-2012`.

      Rust does not consider empty infinite loops to be undefined behavior. However, the
      absence of undefined behavior does not make infinite loops acceptable; they remain
      a liveness and availability hazard.

      Loop termination is generally undecidable (the halting problem), so this rule
      requires engineering judgment and documentation rather than purely automated
      verification.

   .. non_compliant_example::
      :id: non_compl_ex_8dgvuAkXJY4E
      :status: draft

      An unconditional infinite loop with no termination mechanism.

      .. rust-example::
          :no_run:

          fn do_work() {
              println!("Working...");
          }

          fn process() {
              loop {
                  // Non-compliant: no termination condition
                  do_work();
              }
          }

          fn main() {
              process();
          }

   .. non_compliant_example::
      :id: non_compl_ex_uVA40t6CZyZ3
      :status: draft

      This noncompliant example contains a loop whose termination depends on external input
      that may never arrive.

      .. rust-example::

          struct Device {
              ready: bool,
          }

          impl Device {
              fn is_ready(&self) -> bool {
                  self.ready
              }
          }

          fn wait_for_ready(device: &Device) {
              // No timeout, could wait forever
              while !device.is_ready() { // noncompliant
                  // spin
              }
          }

          fn main() {
              let device = Device { ready: true };
              wait_for_ready(&device);
              println!("Device is ready!");
          }

   .. non_compliant_example::
      :id: non_compl_ex_0Z7qk5lZUXed
      :status: draft

      This noncompliant example contains a loop with a termination condition that may never be
      satisfied due to integer overflow.

      .. rust-example::
          :no_run:

          fn process(i: u32) {
              println!("Processing: {}", i);
          }

          fn count_up(target: u32) {
              let mut i: u32 = 0;
              // If target == u32::MAX, wrapping may prevent termination
              // or cause undefined iteration count
              while i <= target { // noncompliant
                  process(i);
                  i = i.wrapping_add(1);
              }
          }

          fn main() {
              // This will loop forever because when i == u32::MAX,
              // i.wrapping_add(1) becomes 0, which is still <= u32::MAX
              count_up(u32::MAX);
          }

   .. non_compliant_example::
      :id: non_compl_ex_dpbVceOhqDqd
      :status: draft

      This noncompliant example contains a loop that depends on a condition modified by
      another thread without guaranteed progress.

      .. rust-example::

          use std::sync::atomic::{AtomicBool, Ordering};

          fn wait_for_signal(flag: &AtomicBool) {
              // Non-compliant: no timeout, relies entirely on external signal
              while !flag.load(Ordering::Acquire) { // noncompliant
                  std::hint::spin_loop();
              }
          }

          fn main() {
              let flag = AtomicBool::new(true);
              wait_for_signal(&flag);
              println!("Signal received!");
          }

   .. non_compliant_example::
      :id: non_compl_ex_ZgwzbE3fqNxr
      :status: draft

      This noncompliant solution contains a main control loop with documented external termination.
      However, this code must still be diagnosed as noncompliant by a conforming analyzer.
      You must follow a formal deviation process to retain this loop.

      .. rust-example::

          use std::sync::atomic::{AtomicBool, Ordering};
          use std::sync::Arc;

          fn pet_watchdog() {
              println!("Petting watchdog...");
          }

          fn read_sensors() {
              println!("Reading sensors...");
          }

          fn compute_control_output() {
              println!("Computing control output...");
          }

          fn write_actuators() {
              println!("Writing actuators...");
          }

          fn safe_shutdown() {
              println!("Safe shutdown complete.");
          }

          /// Main control loop for the safety controller.
          ///
          /// # Termination
          /// This loop terminates when:
          /// - `shutdown` flag is set by the supervisor task
          /// - Hardware watchdog times out (external reset)
          /// - System receives SIGTERM signal
          ///
          /// # WCET
          /// Each iteration completes within 10ms (verified by analysis).
          fn main_control_loop(shutdown: Arc<AtomicBool>) {
              // Compliant: documented main loop with external termination
              while !shutdown.load(Ordering::Acquire) { // noncompliant
                  pet_watchdog();
                  read_sensors();
                  compute_control_output();
                  write_actuators();
              }
              safe_shutdown();
          }

          fn main() {
              let shutdown = Arc::new(AtomicBool::new(true));
              main_control_loop(shutdown);
          }

   .. compliant_example::
      :id: compl_ex_IV9RzXda6kiS
      :status: draft

      This compliant solution contains a simple ``for`` loop with a compile-time bounded iteration count.

      .. rust-example::

          fn process_byte(byte: u8) {
              println!("Processing byte: {}", byte);
          }

          fn process_buffer(buf: &[u8; 256]) {
              // This loop iterates exactly 256 times and is bounded at compile time
              for byte in buf.iter() { // compliant
                  process_byte(*byte);
              }
          }

          fn main() {
              let buf = [0u8; 256];
              process_buffer(&buf);
          }

   .. compliant_example::
      :id: compl_ex_xnlUfp8KIx2g
      :status: draft

      This compliant example contains a loop with an explicit maximum iteration bound.

      .. rust-example::

          const MAX_RETRIES: u32 = 100;

          struct Device {
              ready: bool,
          }

          impl Device {
              fn is_ready(&self) -> bool {
                  self.ready
              }
          }

          #[derive(Debug)]
          enum TimeoutError {
              DeviceNotReady,
          }

          fn delay_microseconds(_us: u32) {
              // Simulate delay
          }

          fn wait_for_ready(device: &Device) -> Result<(), TimeoutError> {
              // Compliant: bounded by MAX_RETRIES
              for _attempt in 0..MAX_RETRIES { // compliant
                  if device.is_ready() {
                      return Ok(());
                  }
                  delay_microseconds(100);
              }
              Err(TimeoutError::DeviceNotReady)
          }

          fn main() {
              let device = Device { ready: true };
              match wait_for_ready(&device) {
                  Ok(()) => println!("Device is ready!"),
                  Err(e) => println!("Error: {:?}", e),
              }
          }

   .. compliant_example::
      :id: compl_ex_hNUMEteSuN3z
      :status: draft

      This compliant example contains a loop with a timeout mechanism.

      .. rust-example::

          use std::time::{Duration, Instant};

          const TIMEOUT: Duration = Duration::from_millis(100);

          struct Device {
              ready: bool,
          }

          impl Device {
              fn is_ready(&self) -> bool {
                  self.ready
              }
          }

          #[derive(Debug)]
          enum TimeoutError {
              Timeout,
          }

          fn wait_for_ready(device: &Device) -> Result<(), TimeoutError> {
              let deadline = Instant::now() + TIMEOUT;

              // Compliant: bounded by wall-clock time
              while Instant::now() < deadline { // compliant
                  if device.is_ready() {
                      return Ok(());
                  }
                  std::hint::spin_loop();
              }
              Err(TimeoutError::Timeout)
          }

          fn main() {
              let device = Device { ready: true };
              match wait_for_ready(&device) {
                  Ok(()) => println!("Device is ready!"),
                  Err(e) => println!("Error: {:?}", e),
              }
          }

   .. compliant_example::
      :id: compl_ex_QIpmVwiWlA8Z
      :status: draft

      This compliant example contains a loop with a provable loop variant
      (a monotonically decreasing value).

      .. rust-example::

          fn binary_search(sorted: &[i32], target: i32) -> Option<usize> {
              let mut low = 0usize;
              let mut high = sorted.len();

              // Compliant: (high - low) monotonically decreases each iteration
              // Loop variant: high - low > 0 and decreases by at least 1
              while low < high { // compliant
                  let mid = low + (high - low) / 2;
                  match sorted[mid].cmp(&target) {
                      std::cmp::Ordering::Equal => return Some(mid),
                      std::cmp::Ordering::Less => low = mid + 1,
                      std::cmp::Ordering::Greater => high = mid,
                  }
                  // Invariant: high - low decreased
              }
              None
          }

          fn main() {
              let data = [1, 3, 5, 7, 9, 11, 13, 15];

              match binary_search(&data, 7) {
                  Some(idx) => println!("Found 7 at index {}", idx),
                  None => println!("7 not found"),
              }

              match binary_search(&data, 6) {
                  Some(idx) => println!("Found 6 at index {}", idx),
                  None => println!("6 not found"),
              }
          }

   .. compliant_example::
      :id: compl_ex_aTONrbCbQN8S
      :status: draft

      This compliant example contains an iterator-based loop with bounded collection size.

      .. rust-example::

          fn sum_values(values: &[i32]) -> i64 {
              let mut total: i64 = 0;

              // Compliant: iterator is bounded by slice length
              for &value in values { // compliant
                  total = total.saturating_add(value as i64);
              }
              total
          }

          fn main() {
              let data = [10, 20, 30, 40, 50];
              let sum = sum_values(&data);
              println!("Sum: {}", sum);
          }

   .. bibliography::
      :id: bib_89X5t6YSqiGE
      :status: draft

      .. list-table::
         :header-rows: 0
         :widths: auto
         :class: bibliography-table

         * - :bibentry:`gui_Ncdb5PhhiZyX:DO-178C`
           - RTCA, Inc. "DO-178C: Software Considerations in Airborne Systems and Equipment Certification." https://store.accuristech.com/standards/rtca-do-178c?product_id=2200105
         * - :bibentry:`gui_Ncdb5PhhiZyX:FLS-LOOPS`
           - Ferrous Systems. "Infinite Loops." *Ferrocene Language Specification*. https://rust-lang.github.io/fls/expressions.html#infinite-loops
         * - :bibentry:`gui_Ncdb5PhhiZyX:ISO-26262`
           - International Organization for Standardization. "ISO 26262: Road Vehicles Functional Safety." https://www.iso.org/standard/43464.html
         * - :bibentry:`gui_Ncdb5PhhiZyX:IEC-61508`
           - International Electrotechnical Commission. "IEC 61508: Functional Safety of Electrical/Electronic/Programmable Electronic Safety-related Systems." https://webstore.ansi.org/standards/iec/iec61508electronicfunctional
         * - :bibentry:`gui_Ncdb5PhhiZyX:MISRA-C-2012`
           - MISRA Consortium. "MISRA C:2012 - Guidelines for the Use of the C Language in Critical Systems." https://misra.org.uk/product/misra-c2012-third-edition-first-revision/
