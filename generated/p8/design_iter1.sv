module fp16_multiplier(
  input  logic [15:0] a,
  input  logic [15:0] b,
  output logic [15:0] result
);

  function automatic logic round_nearest_even_inc(
    input logic lsb,
    input logic guard_bit,
    input logic round_bit,
    input logic sticky_bit
  );
    begin
      round_nearest_even_inc = guard_bit && (round_bit || sticky_bit || lsb);
    end
  endfunction

  always_comb begin
    logic        sign_a;
    logic        sign_b;
    logic [4:0]  exp_a;
    logic [4:0]  exp_b;
    logic [9:0]  frac_a;
    logic [9:0]  frac_b;

    logic        a_is_zero;
    logic        b_is_zero;
    logic        a_is_inf;
    logic        b_is_inf;
    logic        a_is_nan;
    logic        b_is_nan;

    logic        sign_out;
    logic [10:0] mant_a;
    logic [10:0] mant_b;
    logic [21:0] mant_prod;
    logic [31:0] wide_prod;

    integer      exp_a_eff;
    integer      exp_b_eff;
    integer      exp_sum;
    integer      lead_pos;
    integer      shift_amt;
    integer      unbiased_exp;
    integer      unbiased_exp_round;
    integer      sub_shift;
    integer      i;

    logic        found_one;
    logic [10:0] sig11;
    logic [11:0] sig11_rounded;
    logic [31:0] sub_frac_base;
    logic [31:0] sub_frac_rounded;
    logic        guard_bit;
    logic        round_bit;
    logic        sticky_bit;

    sign_a   = a[15];
    sign_b   = b[15];
    exp_a    = a[14:10];
    exp_b    = b[14:10];
    frac_a   = a[9:0];
    frac_b   = b[9:0];

    a_is_zero = (exp_a == 5'd0)  && (frac_a == 10'd0);
    b_is_zero = (exp_b == 5'd0)  && (frac_b == 10'd0);
    a_is_inf  = (exp_a == 5'h1F) && (frac_a == 10'd0);
    b_is_inf  = (exp_b == 5'h1F) && (frac_b == 10'd0);
    a_is_nan  = (exp_a == 5'h1F) && (frac_a != 10'd0);
    b_is_nan  = (exp_b == 5'h1F) && (frac_b != 10'd0);

    sign_out = sign_a ^ sign_b;
    result   = 16'h0000;

    if (a_is_nan || b_is_nan) begin
      result = 16'h7E00;
    end else if ((a_is_inf && b_is_zero) || (b_is_inf && a_is_zero)) begin
      result = 16'h7E00;
    end else if (a_is_inf || b_is_inf) begin
      result = {sign_out, 5'h1F, 10'd0};
    end else if (a_is_zero || b_is_zero) begin
      result = {sign_out, 15'd0};
    end else begin
      mant_a = (exp_a == 5'd0) ? {1'b0, frac_a} : {1'b1, frac_a};
      mant_b = (exp_b == 5'd0) ? {1'b0, frac_b} : {1'b1, frac_b};

      exp_a_eff = (exp_a == 5'd0) ? -14 : (exp_a - 15);
      exp_b_eff = (exp_b == 5'd0) ? -14 : (exp_b - 15);
      exp_sum   = exp_a_eff + exp_b_eff;

      mant_prod = mant_a * mant_b;
      wide_prod = {10'd0, mant_prod};

      if (mant_prod == 22'd0) begin
        result = {sign_out, 15'd0};
      end else begin
        lead_pos = 0;
        found_one = 1'b0;
        for (i = 21; i >= 0; i = i - 1) begin
          if (!found_one && mant_prod[i]) begin
            lead_pos  = i;
            found_one = 1'b1;
          end
        end

        unbiased_exp = exp_sum + lead_pos - 20;

        if (unbiased_exp > 15) begin
          result = {sign_out, 5'h1F, 10'd0};
        end else if (unbiased_exp >= -14) begin
          shift_amt = lead_pos - 10;
          sig11     = mant_prod >> shift_amt;

          guard_bit  = 1'b0;
          round_bit  = 1'b0;
          sticky_bit = 1'b0;

          if (shift_amt > 0) begin
            guard_bit = mant_prod[shift_amt - 1];
          end
          if (shift_amt > 1) begin
            round_bit = mant_prod[shift_amt - 2];
          end
          for (i = 0; i < 22; i = i + 1) begin
            if ((i <= (shift_amt - 3)) && mant_prod[i]) begin
              sticky_bit = 1'b1;
            end
          end

          sig11_rounded    = {1'b0, sig11};
          if (round_nearest_even_inc(sig11[0], guard_bit, round_bit, sticky_bit)) begin
            sig11_rounded = {1'b0, sig11} + 12'd1;
          end

          unbiased_exp_round = unbiased_exp;
          if (sig11_rounded == 12'd2048) begin
            sig11_rounded       = 12'd1024;
            unbiased_exp_round  = unbiased_exp_round + 1;
          end

          if (unbiased_exp_round > 15) begin
            result = {sign_out, 5'h1F, 10'd0};
          end else begin
            result = {sign_out, unbiased_exp_round[4:0] + 5'd15, sig11_rounded[9:0]};
          end
        end else begin
          sub_shift = -(exp_sum + 4);

          if (sub_shift <= 0) begin
            if (-sub_shift >= 32) begin
              sub_frac_base = 32'd0;
            end else begin
              sub_frac_base = wide_prod << (-sub_shift);
            end
            guard_bit  = 1'b0;
            round_bit  = 1'b0;
            sticky_bit = 1'b0;
          end else begin
            if (sub_shift >= 32) begin
              sub_frac_base = 32'd0;
            end else begin
              sub_frac_base = wide_prod >> sub_shift;
            end

            guard_bit  = 1'b0;
            round_bit  = 1'b0;
            sticky_bit = 1'b0;

            if ((sub_shift - 1) < 32) begin
              guard_bit = wide_prod[sub_shift - 1];
            end
            if ((sub_shift - 2) >= 0 && (sub_shift - 2) < 32) begin
              round_bit = wide_prod[sub_shift - 2];
            end
            for (i = 0; i < 32; i = i + 1) begin
              if ((i <= (sub_shift - 3)) && wide_prod[i]) begin
                sticky_bit = 1'b1;
              end
            end
          end

          sub_frac_rounded = sub_frac_base;
          if (round_nearest_even_inc(sub_frac_base[0], guard_bit, round_bit, sticky_bit)) begin
            sub_frac_rounded = sub_frac_base + 32'd1;
          end

          if (sub_frac_rounded >= 32'd1024) begin
            result = {sign_out, 5'd1, 10'd0};
          end else if (sub_frac_rounded == 32'd0) begin
            result = {sign_out, 15'd0};
          end else begin
            result = {sign_out, 5'd0, sub_frac_rounded[9:0]};
          end
        end
      end
    end
  end

endmodule
