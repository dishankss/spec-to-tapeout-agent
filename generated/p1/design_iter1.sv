module seq_detector_0011(
    input clk,
    input reset,
    input data_in,
    output reg detected
);

reg [1:0] state;

localparam [1:0]
    S_IDLE = 2'b00,
    S_0    = 2'b01,
    S_00   = 2'b10,
    S_001  = 2'b11;

always @(posedge clk or posedge reset) begin
    if (reset) begin
        state <= S_IDLE;
        detected <= 1'b0;
    end else begin
        detected <= 1'b0;
        case (state)
            S_IDLE: begin
                if (data_in == 1'b0)
                    state <= S_0;
                else
                    state <= S_IDLE;
            end

            S_0: begin
                if (data_in == 1'b0)
                    state <= S_00;
                else
                    state <= S_IDLE;
            end

            S_00: begin
                if (data_in == 1'b0)
                    state <= S_00;
                else
                    state <= S_001;
            end

            S_001: begin
                if (data_in == 1'b1) begin
                    state <= S_IDLE;
                    detected <= 1'b1;
                end else begin
                    state <= S_0;
                end
            end

            default: begin
                state <= S_IDLE;
                detected <= 1'b0;
            end
        endcase
    end
end

endmodule
